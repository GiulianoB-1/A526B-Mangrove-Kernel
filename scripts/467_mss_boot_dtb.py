#!/usr/bin/env python3
"""P467 exact TG MSS 5.10 DTB, atop P461 final ADSP CB-only ECC48 DTB.
MSS is MANUAL; only QRTR IPCRTR and glink_ssr, no modem FastRPC/DS/IPA.
Do not touch existing ADSP, SMMU, P460B, H0, DTBO or SCM knobs.
"""
import argparse,hashlib,json,runpy,sys,tempfile
from pathlib import Path
sys.path.insert(0,"scripts")
lib=runpy.run_path("scripts/451_dsp_boot_dtb.py")
run=lib["run"];optional=lib["optional"];cells=lib["cells"]
putx=lib["putx"];puts=lib["puts"];new=lib["new"];children=lib["children"]
inspect=runpy.run_path("scripts/458_pstore_ecc48_dtb.py")["inspect"]

MSS="/soc/qcom,mss@4080000"
ORIG="/soc/qcom,glink/modem"
EDGE=MSS+"/glink-edge"
RMTFS="/soc/qcom,rmtfs_sharedmem@0"
AOSS="/soc/qcom,qmp-aop@c300000"

def get(p,node,prop,ty="s"):
    return optional("fdtget","-t",ty,p,node,prop)
def cell(p,node,prop):
    o=get(p,node,prop,"x")
    return [int(x,16) for x in o.split()] if o is not None else None
def present(p,node):
    return get(p,node,"compatible") is not None

def check(p):
    if get(p,MSS,"compatible")!="qcom,sm6350-mss-pas":
        raise RuntimeError("P467 MSS 5.10 PAS DT compatible mismatch")
    if get(p,MSS,"firmware-name")!="modem.mdt":
        raise RuntimeError("P467 MSS firmware name mismatch")
    a=cell(p,AOSS,"phandle")
    cx=cell(p,MSS,"vdd_cx-supply")
    mx=cell(p,MSS,"vdd_mss-supply")
    if not a or not cx or not mx or cx==mx:
        raise RuntimeError("P467 MSS required distinct TG CX/MSS supplies")
    if cell(p,MSS,"cx-supply")!=cx or cell(p,MSS,"px-supply")!=mx:
        raise RuntimeError("P467 MSS 5.10 supply alias moved")
    if cell(p,MSS,"power-domains")!=[a[0],2]:
        raise RuntimeError("P467 MSS AOSS load_state modem=2 absent")
    if get(p,MSS,"power-domain-names")!="load_state":
        raise RuntimeError("P467 MSS AOSS power-domain name mismatch")
    for prop in ("qcom,vdd_cx-uV-uA","qcom,vdd_mss-uV-uA"):
        val=cell(p,MSS,prop)
        if not val or len(val)!=2 or val[0]!=0x180:
            raise RuntimeError("P467 MSS non-TG level384 rail "+prop)
    if get(p,MSS,"interrupt-names").split()!=[
        "wdog","fatal","ready","handover","stop-ack","shutdown-ack"]:
        raise RuntimeError("P467 MSS IRQ names don't preserve optional bit7")
    if get(p,MSS,"qcom,smem-state-names")!="stop":
        raise RuntimeError("P467 MSS SMP2P master stop state mismatch")
    if cell(p,MSS,"memory-region")!=cell(p,"/reserved-memory/modem_region@8b800000","phandle"):
        raise RuntimeError("P467 MSS firmware reservation linkage mismatch")
    if cell(p,"/reserved-memory/modem_region@8b800000","reg")!=[0,0x8b800000,0,0xf800000]:
        raise RuntimeError("P467 MSS firmware memory changed")
    if cell(p,EDGE,"qcom,remote-pid")!=[1]:
        raise RuntimeError("P467 MSS GLINK remote PID != 1")
    if cell(p,EDGE,"mboxes")!=cell(p,ORIG,"mboxes"):
        raise RuntimeError("P467 MSS GLINK mailbox wiring changed")
    if cell(p,EDGE,"interrupts")!=cell(p,ORIG,"interrupts"):
        raise RuntimeError("P467 MSS GLINK IRQ wiring changed")
    if cell(p,EDGE,"interrupts")[0]!=2:
        raise RuntimeError("P467 MSS IPCC client != 2")
    channels=[get(p,EDGE+"/"+kid,"qcom,glink-channels") for kid in children(p,EDGE)]
    if sorted(channels)!=["IPCRTR","glink_ssr"]:
        raise RuntimeError("P467 MSS only IPCRTR+glink_ssr allowed "+repr(channels))
    if get(p,ORIG,"status")!="disabled":
        raise RuntimeError("P467 MSS duplicate legacy GLINK transport owner")
    if get(p,RMTFS,"compatible")!="qcom,sharedmem-uio":
        raise RuntimeError("P467 RMTFS wrong vendor UIO binding")
    if cell(p,RMTFS,"reg")!=[0,0x280000] or cell(p,RMTFS,"qcom,client-id")!=[1]:
        raise RuntimeError("P467 RMTFS region/client mismatch")
    if "qcom,guard-memory" not in run("fdtget","-p",p,RMTFS).splitlines():
        raise RuntimeError("P467 RMTFS guard-memory absent")
    if get(p,RMTFS,"status")!="okay":
        raise RuntimeError("P467 RMTFS disabled")
    if inspect(p,patched=True)["ecc_size"]!=[48]:
        raise RuntimeError("P467 lost P461 ECC48 pstore")
    if get(p,"/soc/qcom,lpass@3000000","compatible")!="qcom,sm6350-adsp-pas":
        raise RuntimeError("P467 changed ADSP PAS compatible")
    if get(p,"/firmware/scm","status")!="disabled":
        raise RuntimeError("P467 changed manual SCM knob")
    return {"MSS":MSS,"compatible":"qcom,sm6350-mss-pas",
            "auto_boot":"descriptor false","firmware":"modem.mdt",
            "pas_id":4,"smem":421,"sysmon":"modem","ssctl":18,
            "region":["0x8b800000","0xf800000"],"cx_supply":cx[0],
            "mss_supply":mx[0],"rails_level":384,
            "AOSS_LOAD_STATE_MODEM":2,
            "glink_channels":channels,"glink_remote_pid":1,
            "ipcc_client":2,"rmtfs":"0x280000 client 1 /dev/uio0 ABI",
            "shutdown_ack_bit7":"present in DTS; 5.10 q6v5 does not request a handler",
            "IPA":"OFF","modem_FastRPC":"OFF","glinkpkt_DATA":"OFF",
            "ICNSS":"OFF","P463_guard":"unchanged","ECC48":True}

def transform(p):
    if get(p,MSS,"compatible")!="qcom,pil-tz-generic":
        raise RuntimeError("P467 refusing non-TG original MSS node")
    if get(p,ORIG,"status")=="disabled":
        raise RuntimeError("P467 refusing already-consumed MPSS GLINK")
    if get(p,EDGE,"qcom,remote-pid") is not None:
        raise RuntimeError("P467 MSS transport already staged")
    for prop in ("qcom,vdd_cx-uV-uA","qcom,vdd_mss-uV-uA"):
        value=cell(p,MSS,prop)
        if not value or value[0]!=0x180:
            raise RuntimeError("P467 refusing non-TG PM6150a S1/S6 regulator level")
    a=cell(p,AOSS,"phandle")
    if not a or len(a)!=1:
        raise RuntimeError("P467 missing exclusive AOSS qmp power-domain provider")
    cx=cell(p,MSS,"vdd_cx-supply")[0]
    mss=cell(p,MSS,"vdd_mss-supply")[0]
    putx(p,MSS,"cx-supply",cx)
    putx(p,MSS,"px-supply",mss)
    putx(p,MSS,"power-domains",a[0],2)
    puts(p,MSS,"power-domain-names","load_state")
    puts(p,MSS,"firmware-name","modem.mdt")
    puts(p,MSS,"compatible","qcom,sm6350-mss-pas")
    # Keep all 6 physical interrupts as in TG. The first 5 are requested
    # by 5.10 q6v5; shutdown-ack bit7 remains unhandled, not fabricated.
    puts(p,MSS,"interrupt-names","wdog","fatal","ready","handover",
         "stop-ack","shutdown-ack")
    puts(p,MSS,"qcom,smem-state-names","stop")
    new(p,EDGE)
    putx(p,EDGE,"qcom,remote-pid",1)
    for prop in ("mboxes","interrupt-parent","interrupts"):
        putx(p,EDGE,prop,*cell(p,ORIG,prop))
    copied=[]
    for ch in children(p,ORIG):
        prev=ORIG+"/"+ch
        name=get(p,prev,"qcom,glink-channels")
        if name not in ("IPCRTR","glink_ssr"):continue
        dst=EDGE+"/"+ch;new(p,dst)
        for prop in run("fdtget","-p",p,prev).splitlines():
            if prop in ("phandle","linux,phandle","qcom,notify-edges"):
                continue
            v=run("fdtget","-t","bx",p,prev,prop)
            run("fdtput","-t","bx",p,dst,prop,*v.split())
            if run("fdtget","-t","bx",p,dst,prop)!=v:
                raise RuntimeError("P467 MSS GLINK channel property changed "+prop)
        copied.append(name)
    if sorted(copied)!=["IPCRTR","glink_ssr"]:
        raise RuntimeError("P467 MSS could not copy TG modem channels "+repr(copied))
    puts(p,ORIG,"status","disabled")
    if get(p,RMTFS,"compatible")!="qcom,sharedmem-uio":
        raise RuntimeError("P467 MSS wrong RMTFS DT node: no upstream substitute")
    puts(p,RMTFS,"status","okay")
    return check(p)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--dtb-in",required=True,type=Path)
    p.add_argument("--dtb-out",required=True,type=Path)
    p.add_argument("--report",required=True,type=Path)
    p.add_argument("--check-only",action="store_true")
    args=p.parse_args()
    if args.check_only:
        result=check(args.dtb_in)
        args.dtb_out.write_bytes(args.dtb_in.read_bytes())
    else:
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/"mss.dtb";f.write_bytes(args.dtb_in.read_bytes())
            result=transform(f)
            args.dtb_out.write_bytes(f.read_bytes())
    result["dtb_sha256"]=hashlib.sha256(args.dtb_out.read_bytes()).hexdigest()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n")
    print("P467 MSS DTB BOOT STAGING PASS "+json.dumps(result,sort_keys=True))
if __name__=="__main__":main()
