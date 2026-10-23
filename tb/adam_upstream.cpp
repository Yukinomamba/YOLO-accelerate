#include "Vadam_upstream.h"
#include "verilated.h"
#include "../software/adam_upstream_abi.h"
#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <random>
#include <vector>

static Vadam_upstream d;
static std::vector<uint64_t> output;
static unsigned last_count=0;
static uint64_t clocks=0;
static void check(bool ok, const char* what) {
    if (!ok) { std::cerr << "FAIL " << what << " cycle=" << clocks << '\n'; std::exit(1); }
}
static void tick() {
    d.clk=0; d.eval();
    if (d.M_AXIS_tvalid && d.M_AXIS_tready) {
        output.push_back(d.M_AXIS_tdata);
        last_count += d.M_AXIS_tlast;
    }
    d.clk=1; d.eval(); ++clocks;
    d.clk=0; d.eval();
}
static void idle(unsigned n=8) { while(n--) tick(); }
static void wr(unsigned addr, uint32_t value) {
    d.S_AXI_LITE_CTRL_awaddr=addr; d.S_AXI_LITE_CTRL_wdata=value;
    d.S_AXI_LITE_CTRL_wstrb=15; d.S_AXI_LITE_CTRL_awvalid=1; d.S_AXI_LITE_CTRL_wvalid=1;
    unsigned timeout=100;
    while(!(d.S_AXI_LITE_CTRL_awready && d.S_AXI_LITE_CTRL_wready) && --timeout) tick();
    check(timeout,"CSR write ready"); tick();
    d.S_AXI_LITE_CTRL_awvalid=0; d.S_AXI_LITE_CTRL_wvalid=0;
    timeout=100; while(!d.S_AXI_LITE_CTRL_bvalid && --timeout) tick();
    check(timeout && !d.S_AXI_LITE_CTRL_bresp,"CSR write response"); tick();
}
static void task(uint32_t config, unsigned action) {
    adam_begin_task([](void*, unsigned addr, uint32_t val) {wr(addr,val);}, nullptr, config, action);
}
static void done() {
    unsigned timeout=20000; while(!d.ap_done && --timeout) tick();
    check(timeout,"task completion"); idle();
}
static void load(uint32_t config, unsigned kind, const std::vector<uint64_t>& words, bool bubbles=false) {
    task(config|(kind<<2),ADAM_RECV);
    for(size_t i=0;i<words.size();++i) {
        d.S_AXIS_tvalid=0; d.S_AXIS_tlast=0;
        if(bubbles && i%3==0) idle(2);
        unsigned timeout=100; while(!d.S_AXIS_tready && --timeout) tick();
        check(timeout,"stream input ready");
        d.S_AXIS_tdata=words[i]; d.S_AXIS_tlast=i+1==words.size(); d.S_AXIS_tvalid=1; tick();
    }
    d.S_AXIS_tvalid=0; d.S_AXIS_tlast=0; done();
}
int main(int argc,char** argv) {
    Verilated::commandArgs(argc,argv);
    std::mt19937 rng(0x20261023);
    d.M_AXIS_tready=1; d.S_AXI_LITE_CTRL_bready=1; d.S_AXI_LITE_CTRL_rready=1;
    d.rst=1; idle(); d.rst=0; idle();
    unsigned checked=0;
    const unsigned widths[]={15,28,54,106,210,418},height=7;
    for(unsigned test=0;test<24;test++) {
        unsigned width=widths[test%6];
        bool two_groups=test%4==0;
        bool lut=test%2==1;
        bool extreme=test>=12;
        uint32_t shape=adam_shape(height,test%6)|(lut?0:ADAM_RELU);
        unsigned bank=test&1;
        int8_t weights[8][8][9]={};
        for(unsigned o=0;o<8;o++) for(unsigned i=0;i<8;i++) for(unsigned k=0;k<9;k++)
            if(test%3!=0 || k==4) weights[o][i][k]=extreme?int(rng()%256)-128:int(rng()%3)-1;
        uint64_t packed[72]; adam_pack_weights(weights,packed);
        load(shape,ADAM_WEIGHT,std::vector<uint64_t>(packed,packed+72));
        std::vector<uint64_t> biases; int32_t bias[8];
        for(unsigned o=0;o<8;o++) { bias[o]=extreme?int(rng()%262144)-131072:int(rng()%9)-4; biases.push_back(adam_pack_bias(bias[o])); }
        load(shape,ADAM_BIAS,biases);
        if(lut) {
            std::vector<uint64_t> table;
            // Deliberately nonzero LUT[0] tests the full activation-table path.
            for(unsigned i=0;i<256;i++) table.push_back((i*13+7)&255);
            load(shape,ADAM_ACTIVATION,table);
        }
        std::vector<int8_t> input(height*width*8);
        std::vector<uint64_t> pixels;
        for(unsigned y=0;y<height;y++) for(unsigned x=0;x<width;x++) {
            int8_t lanes[8];
            for(unsigned i=0;i<8;i++) {
                lanes[i]=(x==0||y==0||x+1==width||y+1==height)?0:
                    (extreme?int(rng()%256)-128:int(rng()%7)-3);
                input[(y*width+x)*8+i]=lanes[i];
            }
            pixels.push_back(adam_pack_pixel(lanes));
        }
        load(shape|(bank?ADAM_BANK:0),ADAM_IFM,pixels,true);
        wr(ADAM_SCALE,adam_quant_config(32767,0)); wr(ADAM_ZERO,0); wr(ADAM_ADDR,0);
        if(two_groups) {
            task(shape|(bank?0:ADAM_BANK)|ADAM_FIRST,ADAM_CONV); done();
        }
        uint32_t config=shape|(bank?0:ADAM_BANK)|(two_groups?0:ADAM_FIRST)|ADAM_LAST;
        task(config,ADAM_CONV); done();
        output.clear();last_count=0;
        task(config,ADAM_SEND);done();
        check(output.size()==height*width,"output frame length");
        check(last_count==1,"output TLAST count");
        for(unsigned y=0;y<height;y++) for(unsigned x=0;x<width;x++) for(unsigned o=0;o<8;o++) {
            int sum=0;
            if(x>0 && y>0 && x+1<width && y+1<height) {
                sum=bias[o];
                for(unsigned ky=0;ky<3;ky++) for(unsigned kx=0;kx<3;kx++) for(unsigned i=0;i<8;i++)
                    sum+=(two_groups?2:1)*input[(((y+ky-1)*width+x+kx-1)*8)+i]*weights[o][i][ky*3+kx];
            }
            // Original datapath wraps at 18 bits, saturates to 16 bits, then
            // multiplies by signed Q15 scale and rounds ties toward +infinity.
            sum &= 0x3ffff; if(sum & 0x20000) sum-=0x40000;
            int64_t product=int64_t(std::clamp(sum,-32768,32767))*32767;
            int64_t q=product/32768, rem=product%32768;
            if(rem<0) { --q; rem+=32768; }
            if(rem>=16384) ++q;
            int quant=std::clamp(int(q),-128,127);
            int want=lut?(((quant&255)*13+7)&255):std::max(quant,0);
            int got=(output[y*width+x]>>(8*o))&255;
            if(got!=want) { std::cerr<<"case="<<test<<" y="<<y<<" x="<<x<<" o="<<o<<" got="<<got<<" want="<<want<<'\n'; return 1; }
            ++checked;
        }
    }
    std::cout<<"PASS original Accel_Conv: 24 CSR/AXIS convolution frames, "<<checked
             <<" INT8 values, six native widths, 8/16 input channels, 1x1 embedding, 3x3, both input banks, IFM bubbles, signed extremes, 18-bit wrap, saturation, bias, ReLU/LUT; clocks="<<clocks<<'\n';
}
