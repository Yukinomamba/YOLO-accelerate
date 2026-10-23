#include "Vnpu_postprocess.h"
#include "verilated.h"
#include "npu_reference.h"
#include <iostream>
#include <random>

class Bench {
    static VerilatedContext* single_thread(VerilatedContext& c) { c.threads(1); return &c; }
public:
    VerilatedContext context;
    Vnpu_postprocess d{single_thread(context)};
    std::mt19937 random{0x1282026};
    std::array<uint32_t,16> m{};
    std::array<unsigned,16> s{};
    std::array<uint8_t,256> table = silu_table();
    uint64_t vectors=0, values=0, errors=0, aborts=0, cycles=0;
    Bench() { reset(); }
    void eval() { d.clk=0; d.eval(); }
    void tick() { eval(); d.clk=1; d.eval(); ++cycles; }
    void reset() {
        d.in_valid=0; d.cfg_valid=0; d.out_ready=0; d.rst=1; eval();
        require(!d.in_ready && !d.cfg_ready && !d.out_valid,"reset handshakes");
        tick(); tick(); d.rst=0; eval();
        m.fill(1); s.fill(0);
        require(!d.busy && !d.lut_ready,"reset state");
    }
    void cfg(unsigned kind, unsigned addr, uint32_t data, bool valid=true) {
        d.cfg_kind=kind; d.cfg_addr=addr; d.cfg_data=data; d.cfg_valid=1;
        d.in_valid=1; eval();
        require(d.cfg_ready && !d.in_ready,"configuration priority");
        tick(); d.cfg_valid=0; d.in_valid=0;
        require(bool(d.cfg_error)==!valid,"configuration validation");
        if (!valid) ++errors;
        tick(); require(!d.cfg_error,"configuration error must pulse");
    }
    void scales(uint32_t multiplier, unsigned shift) {
        for (unsigned oc=0; oc<16; ++oc) {
            m[oc]=multiplier; s[oc]=shift;
            cfg(0,oc,m[oc]); cfg(1,oc,s[oc]);
        }
    }
    void load_lut() {
        for (unsigned i=0; i<256; ++i) {
            cfg(2,i,table[i]);
            require(bool(d.lut_ready)==(i==255),"incomplete LUT became usable");
        }
    }
    void launch(const std::array<uint32_t,16>& x, unsigned mode, uint16_t mask) {
        d.in_mode=mode; d.in_mask=mask; d.in_x=vectors&255; d.in_y=(vectors>>8)&255;
        d.in_last=vectors&1;
        for (unsigned oc=0; oc<16; ++oc) d.in_data[oc]=x[oc];
        d.in_valid=1; eval(); require(d.in_ready,"input not accepted"); tick(); d.in_valid=0;
    }
    void run(const std::array<uint32_t,16>& x, unsigned mode, uint16_t mask=0xffff) {
        launch(x,mode,mask);
        bool done=false, held=false;
        std::array<uint32_t,4> previous{};
        unsigned stalls=0;
        const uint64_t deadline=cycles+100;
        while (!done && cycles<deadline) {
            // Attempts to rewrite coefficients or submit a vector while this one is active.
            d.cfg_valid=1; d.cfg_kind=0; d.cfg_addr=0; d.cfg_data=0;
            d.in_valid=1; d.in_mask=0; d.in_mode=0;
            d.out_ready=random()%3!=0;
            if (d.out_valid && stalls<4) { d.out_ready=0; ++stalls; }
            eval();
            require(!d.cfg_ready && !d.in_ready && !d.cfg_error,"busy input/config accepted");
            if (held) {
                require(d.out_valid,"output valid dropped under backpressure");
                for (unsigned j=0;j<4;++j) require(d.out_int8[j]==previous[j],"stalled payload changed");
            }
            held=d.out_valid && !d.out_ready;
            if (d.out_valid) {
                require(d.out_mode==mode && d.out_mask==mask && d.out_x==(vectors&255) &&
                        d.out_y==((vectors>>8)&255) && d.out_last==(vectors&1),"output metadata");
                for (unsigned oc=0;oc<16;++oc) {
                    require(d.out_raw[oc]==x[oc],"raw value changed");
                    const uint8_t q=uint8_t(requant_reference(signed32(x[oc]),m[oc],s[oc]));
                    const uint8_t expected=mode==0 || !(mask&(1u<<oc)) ? 0 : mode==2 ? table[q] : q;
                    require(uint8_t(d.out_int8[oc/4]>>(8*(oc%4)))==expected,"requant/LUT mismatch");
                }
                done=d.out_ready;
                for (unsigned j=0;j<4;++j) previous[j]=d.out_int8[j];
            }
            tick();
        }
        d.cfg_valid=0; d.in_valid=0; d.out_ready=0; eval();
        require(done && !d.busy && !d.out_valid,"vector completion/timeout");
        ++vectors; values+=16;
    }
    void test() {
        cfg(0,0,0x80000000u,false); cfg(0,16,1,false);
        cfg(1,0,64,false); cfg(1,16,0,false); cfg(2,1,0,false);
        cfg(2,0,256,false); cfg(3,0,0,false);
        load_lut();
        cfg(2,0,table[0]); require(!d.lut_ready,"LUT reload must invalidate old table");
        cfg(2,2,table[2],false);
        for (unsigned i=1;i<256;++i) cfg(2,i,table[i]);
        require(d.lut_ready,"complete LUT reload");
        const std::array<uint32_t,16> edges={0,1,2,3,126,127,128,129,
            0xffffffffu,0xfffffffeu,0xfffffffdu,0xffffff80u,0xffffff7fu,0x7fffffffu,0x80000000u,0x80000001u};
        for (uint32_t multiplier : {0u,1u,3u,127u,32768u,0x40000000u,0x7fffffffu}) {
            for (unsigned shift=0;shift<64;++shift) {
                scales(multiplier,shift);
                run(edges,1); run(edges,2,uint16_t(random()));
            }
        }
        scales(1,0);
        for (unsigned base=0;base<256;base+=16) {
            std::array<uint32_t,16> x{};
            for (unsigned i=0;i<16;++i) x[i]=uint32_t(base+i<128 ? int(base+i) : int(base+i)-256);
            run(x,2); // Every signed INT8 table address, including negative addresses.
        }
        for (unsigned n=0;n<1000;++n) {
            std::array<uint32_t,16> x{};
            for (unsigned oc=0;oc<16;++oc) {
                m[oc]=random()&0x7fffffffu; s[oc]=random()%64; x[oc]=random();
                cfg(0,oc,m[oc]); cfg(1,oc,s[oc]);
            }
            run(x,n%3,uint16_t(random()));
        }
        for (unsigned delay=0;delay<12;++delay) {
            launch(edges,1,0xffff);
            for (unsigned i=0;i<delay;++i) tick();
            reset();
            for (unsigned i=0;i<16;++i) { tick(); require(!d.out_valid && !d.busy,"aborted vector survived reset"); }
            run(edges,1); ++aborts;
        }
    }
};

int main() {
    try {
        Bench b; b.test();
        std::cout<<"PASS npu_postprocess: "<<b.vectors<<" vectors, "<<b.values
                 <<" values, all 64 shifts, 256 LUT addresses, "<<b.errors
                 <<" invalid configurations, "<<b.aborts<<" reset recoveries\n";
    } catch (const std::exception& e) { std::cerr<<"FAIL "<<e.what()<<'\n'; return 1; }
}
