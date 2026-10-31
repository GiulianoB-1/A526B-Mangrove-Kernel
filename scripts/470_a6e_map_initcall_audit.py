#!/usr/bin/env python3
"""P470-A6e: fail-closed proof from the REAL native System.map, no runtime claim."""
import argparse
import json
import re
from pathlib import Path

REQUIRED = (
    "ipa_clients_manager_init",
    "ipa3_notify_clients_registered",
    "ipa3_register_to_fmwk",
    "ipa_fmwk_register_ipa",
    "ipa3_ready_cb",
    "rndis_ipa_init",
    "rndis_ipa_cleanup",
    "rndis_ipa_pipe_connect_notify",
    "rndis_ipa_pipe_disconnect_notify",
)
INITCALLS = {
    "ipa_module_init": "ipa_module_init4",
    "ipa_clients_manager_init": "ipa_clients_manager_init4",
}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--system-map",required=True,type=Path)
    p.add_argument("--build",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    mapping={}
    for line in a.system_map.read_text().splitlines():
        m=re.match(r"^([0-9a-fA-F]+)\s+([a-zA-Z])\s+(\S+)$",line)
        if m:
            addr,typ,name=m.groups()
            mapping.setdefault(name,[]).append({"address":int(addr,16),"type":typ})
    symbols={}
    for name in REQUIRED:
        vals=mapping.get(name,[])
        if len(vals)!=1:
            raise RuntimeError(f"P470-A6e System.map {name} count={len(vals)}")
        symbols[name]=vals[0]
    init={}
    for name,suffix in INITCALLS.items():
        matching=[(k,v[0]) for k,v in mapping.items()
                  if k.startswith("__initcall_") and k.endswith(suffix)]
        if len(matching)!=1:
            raise RuntimeError(f"P470-A6e expected exactly one subsys initcall {name}, got {matching}")
        init[name]={"symbol":matching[0][0],**matching[0][1]}
    if not init["ipa_module_init"]["address"] < init["ipa_clients_manager_init"]["address"]:
        raise RuntimeError("P470-A6e BAD initcall order: clients before IPA ctx allocation")
    # In this native built-in Kbuild, composite -objs are expanded into
    # individual members of the directory's thin built-in.a archive.
    # Requiring ipa_clientsm.o or rndisipam.o as standalone intermediates
    # incorrectly rejects a successful Image link. We instead require the
    # archive, every real compiled constituent, and the linked System.map
    # symbols and initcall order already verified above.
    archive = a.build / "drivers/platform/msm/ipa/ipa_clients/built-in.a"
    if not archive.is_file() or archive.stat().st_size < 8:
        raise RuntimeError("P470-A6e missing real IPA clients built-in.a archive")
    objects = (
        "ipa_clients_manager.o",
        "ipa_usb.o",
        "ipa_wdi3.o",
        "ipa_gsb.o",
        "ipa_uc_offload.o",
        "ipa_wigig.o",
        "ipa_mhi_client.o",
        "rndis_ipa.o",
    )
    objdir = a.build / "drivers/platform/msm/ipa/ipa_clients"
    for obj in objects:
        if not (objdir / obj).is_file():
            raise RuntimeError("P470-A6e missing compiled IPA clients member "+obj)
    compiled_members = [str(objdir / obj) for obj in objects]
    report={
        "phase":"P470-A6e-REAL-COMPILED-IPA-CLIENTS-ORDER",
        "symbols":symbols,
        "subsys_initcalls":init,
        "core_initcall_before_clients_initcall":True,
        "ipa_clients_manager_present_in_native_system_map":True,
        "real_rndis_ipa_builtin_and_symbols_present":True,
        "compiled_clients_archive":str(archive),
        "compiled_clients_members":compiled_members,
        "link_proof":"native System.map symbols and ordered subsys initcalls",
        "composite_o_intermediate_not_required_for_builtin_archive":True,
        "qmi_service_runtime_started":False,
        "hardware_stability_unverified":True,
        "ipa_disarmed_default":True,
    }
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print("P470-A6e NATIVE System.map PASS: real ipa_clients_manager_init linked AFTER IPA core initcall")
if __name__=="__main__":
    main()
