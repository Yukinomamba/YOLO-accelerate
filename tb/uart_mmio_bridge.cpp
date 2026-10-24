#include "Vuart_mmio_bridge.h"
#include "verilated.h"
#include <iostream>
#include <stdexcept>
#include <vector>
static void check(bool x,const char* message) { if (!x) throw std::runtime_error(message); }
static uint16_t crc(const std::vector<uint8_t>& b,unsigned start,unsigned end) {
    uint16_t c=0xffff;
    for (unsigned i=start;i<end;i++) {
        c^=uint16_t(b[i])<<8;
        for (unsigned bit=0;bit<8;bit++) c=uint16_t((c<<1)^((c&0x8000)?0x1021:0));
    }
    return c;
}
class Bench {
    static VerilatedContext* single(VerilatedContext& c) { c.threads(1); return &c; }
public:
    VerilatedContext c;
    Vuart_mmio_bridge d{single(c)};
    unsigned requests=0,tx_stalls=0;
    Bench() { d.rx_valid=0; d.rx_error=0; d.tx_ready=0; d.req_ready=0; d.rsp_valid=0; d.rsp_error=0; reset(); }
    void eval() { d.clk=0; d.eval(); }
    void tick() { eval(); if (d.req_valid && d.req_ready) ++requests; d.clk=1; d.eval(); }
    void reset() { d.rst=1; tick(); tick(); d.rst=0; eval(); }
    std::vector<uint8_t> frame(unsigned seq,unsigned op,uint32_t data) {
        std::vector<uint8_t> b{0xa5,0x5a,1,uint8_t(seq),uint8_t(op),5,0x60,0};
        for (unsigned i=0;i<4;i++) b.push_back(uint8_t(data>>(8*i)));
        uint16_t x=crc(b,2,12); b.push_back(uint8_t(x)); b.push_back(uint8_t(x>>8)); return b;
    }
    void feed(const std::vector<uint8_t>& b) {
        for (auto x:b) { d.rx_valid=1; d.rx_data=x; tick(); }
        d.rx_valid=0; eval();
    }
    std::vector<uint8_t> response() {
        unsigned wait=0;
        while (!d.tx_valid) { check(++wait<40,"reply timeout"); tick(); }
        std::vector<uint8_t> b;
        for (unsigned i=0;i<12;i++) {
            d.tx_ready=0; eval(); const unsigned held=d.tx_data;
            for (unsigned n=0;n<4;n++) { check(d.tx_valid && d.tx_data==held,"TX data unstable under backpressure"); tick(); ++tx_stalls; }
            b.push_back(d.tx_data); d.tx_ready=1; tick();
        }
        d.tx_ready=0; eval(); check(!d.tx_valid,"extra reply bytes");
        check(b[0]==0x5a && b[1]==0xa5 && b[2]==1 && b[5]==0,"reply header");
        check(crc(b,2,10)==uint16_t(b[10]|unsigned(b[11])<<8),"reply CRC"); return b;
    }
    void test() {
        auto f=frame(19,1,0xaabbccdd); feed(f);
        for (unsigned i=0;i<17;i++) {
            check(d.req_valid && d.req_write && d.req_addr==0x60 && d.req_wstrb==5 && d.req_wdata==0xaabbccdd,"MMIO request held incorrectly");
            tick();
        }
        d.req_ready=1; tick(); check(requests==1 && d.rsp_ready,"request acceptance");
        for (unsigned i=0;i<11;i++) { check(d.rsp_ready && !d.req_valid,"response wait"); tick(); }
        d.rsp_valid=1; d.rsp_rdata=0x89abcdef; tick(); d.rsp_valid=0;
        auto first=response(); check(first[3]==19 && first[4]==0 && first[6]==0xef && first[9]==0x89,"response data");
        feed(f); check(response()==first && requests==1,"duplicate caused a second MMIO request");
        feed(frame(19,1,7)); check(response()[4]==4 && requests==1,"sequence conflict executed");
        auto bad=frame(20,1,0); bad.back()^=1; feed(bad); check(response()[4]==3 && requests==1,"bad CRC executed");
        feed({0xa5,0x5a,1,20}); for (unsigned i=0;i<40;i++) tick();
        feed(frame(20,1,0)); check(d.req_valid,"partial-frame timeout did not recover");
        tick(); d.rsp_valid=1; d.rsp_error=1; d.rsp_rdata=0; tick(); d.rsp_valid=0;
        check(response()[4]==1 && requests==2,"MMIO error reply");
        feed(frame(21,1,0)); check(d.req_valid,"pending request setup"); reset();
        check(!d.req_valid && !d.tx_valid,"reset left an outstanding request");
        check(requests==2,"reset executed a blocked request");
    }
};
int main() {
    try { Bench b; b.test(); std::cout<<"PASS uart_mmio_bridge: held requests/responses, "<<b.tx_stalls<<" TX stall cycles, duplicate/conflict/CRC/timeout/reset; "<<b.requests<<" actual MMIO requests\n"; }
    catch(const std::exception& e) { std::cerr<<"FAIL "<<e.what()<<'\n'; return 1; }
}
