import sys
from bluetooth import *

<<<<<<< HEAD
service_matches = find_service(name = "SpeedLight", uuid = "059c01eb-feaa-0e13-ffc4-f5d6f3be76d9", address="localhost")
=======
service_matches = find_service(name = "SpeedLight", uuid = "059c01eb-feaa-0e13-ffc4-f5d6f3be76d9")
>>>>>>> 7047e5dd7e155d70f81648375df33c8a04af4a43

if len(service_matches) == 0:
  print "cant find"

print service_matches
