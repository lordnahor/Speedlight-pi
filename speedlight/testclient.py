import sys
from bluetooth import *

service_matches = find_service(name = "SpeedLight", uuid = "059c01eb-feaa-0e13-ffc4-f5d6f3be76d9")

if len(service_matches) == 0:
  print "cant find"

print service_matches
