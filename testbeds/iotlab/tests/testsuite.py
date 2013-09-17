#!/usr/bin/env python

import os
from difflib import SequenceMatcher

print "config sfi"
with open ("/root/.sfi/sfi_config", "r") as sfi_config:
	sfi_config_txt = [line for line in sfi_config]

with open("/root/.sfi/sfi_config_iotlab", "r") as sfi_config_iotlab:
	sfi_config_iotlab_txt = [line for line in sfi_config_iotlab]

with open("/root/.sfi/sfi_config_firexp", "r") as sfi_config_firexp:
	sfi_config_firexp_txt  =  [line for line in sfi_config_firexp]
# check that we are using the iotlab sfi configuration
result1 = SequenceMatcher(None, sfi_config_txt, sfi_config_iotlab_txt)

result2 = SequenceMatcher(None, sfi_config_txt, sfi_config_firexp_txt)

if result1.ratio() != 1.0:
	os.system('cp /root/.sfi/sfi_config_iotlab /root/.sfi/sfi_config')

os.system('cat /root/.sfi/sfi_config')
os.system('rm /root/tests_rspecs/iotlab_devlille_OUTPUT.rspec')

print " =================    SFI.PY LIST IOTLAB        ============="
os.system('sfi.py list iotlab')


print " =================    SFI.PY RESOURCES          ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources')


print " ================= SFI.PY RESOURCES -R IOTLAB        ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -r iotlab')


print " =================    SFI.PY RESOURCES -L ALL      ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -l all')

print " ================= SFI.PY RESOURCES -R IOTLAB -L ALL ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -r iotlab -l all')

print " ================= SFI.PY RESOURCES -O  output rspec ==========="
os.system('sfi.py resources -o /root/tests_rspecs/iotlab_devlille_OUTPUT.rspec')

print " ================= SFI.PY RESOURCES -L LEASES  ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -l leases')


print " =================    SFI.PY SHOW USER   ============="
raw_input("Press Enter to continue...")
os.system('sfi.py show iotlab.avakian')

print " =================    SFI.PY SHOW NODE   ============="
os.system('sfi.py show iotlab.node6.devlille.senslab.info')

print " =================    SFI.PY SLICES       ============="
raw_input("Press Enter to continue...")
os.system('sfi.py slices')

print " =================    SFI.PY STATUS SLICE   ============="
os.system('sfi.py status iotlab.avakian_slice')

print " =================    SFI.PY CREATE SLICE  on iotlab only  ============="
raw_input("Press Enter to continue...")
os.system('sfi.py create iotlab.avakian_slice /root/tests_rspecs/iotlab_devlille.rspec')


print " ================= SFI.PY RESOURCES -l all iotlab.avakian_slice ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -l all iotlab.avakian_slice')


print " =================    SFI.PY DELETE SLICE   ============="
raw_input("Press Enter to continue...")
os.system('sfi.py delete iotlab.avakian_slice')


print " =================    SFI.PY CREATE SLICE  on iotlab and firexp  ============="
raw_input("Press Enter to continue...")
os.system('sfi.py create iotlab.avakian_slice /root/tests_rspecs/test_bidir.rspec')


print " ================= SFI.PY RESOURCES -l all -r iotlab iotlab.avakian_slice ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -l all -r iotlab iotlab.avakian_slice')


print " =================SFI.PY RESOURCES -L LEASES -R IOTLAB ============== "
os.system('sfi.py resources -r iotlab -l leases')


print " =================    SFI.PY DELETE SLICE   ============="
raw_input("Press Enter to continue...")
os.system('sfi.py delete iotlab.avakian_slice')

print "\r\n \r\n"

print " *********changing to firexp sfi config ***************"
os.system('cp /root/.sfi/sfi_config_firexp /root/.sfi/sfi_config')



print " =================    SFI.PY CREATE SLICE  on iotlab and firexp  ============="
raw_input("Press Enter to continue...")
os.system('sfi.py create firexp.flab.iotlab_slice /root/tests_rspecs/mynodes.rspec')


print " =================    SFI.PY SHOW SLICE   ============="
raw_input("Press Enter to continue...")
os.system('sfi.py show firexp.flab.iotlab_slice')


print " ================= SFI.PY RESOURCES -l leases firexp.flab.iotlab_slice ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources -l leases firexp.flab.iotlab_slice')


print " ================= SFI.PY RESOURCES firexp.flab.iotlab_slice  ============="
raw_input("Press Enter to continue...")
os.system('sfi.py resources firexp.flab.iotlab_slice')




