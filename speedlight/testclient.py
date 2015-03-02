import sys
from bluetooth import *

service_matches = find_service(name = "SpeedLight", uuid = SERIAL_PORT_CLASS)

if len(service_matches) == 0:
  print "cant find"

print service_matches