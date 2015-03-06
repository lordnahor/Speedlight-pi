from bluetooth import *
from select import *
from threading import Thread, Lock
import shelve, time, json
from Queue import Queue
import hashlib

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "pi"
if "pi" in DEVICE:
  import RPi.GPIO as GPIO
  import pigpio

def uberhash(s):
  return hashlib.sha1(hashlib.md5(s).hexdigest()).hexdigest()

def send(receiver, message):
  receiver.queue.put(message)

class ActiveThread(Thread):
  def __init__(self):
    Thread.__init__(self)
    self.name = str(type(self))
    self.queue = Queue()
    self._stop = False
    self.setDaemon(True)
    self.start()

  def run(self):
    while not self._stop:
      message = self.queue.get()
      print "Executing: ", message[0], type(self)
      self._dispatch(message)
      if message[0] == "die":
        self._stop = Tru

class LEDController(ActiveThread):
  def __init__(self, red, green, blue):
    self.BLUE = blue
    self.RED = red
    self.GREEN = green
    if "pi" in DEVICE:
      self.pi = pigpio.pi()
      self.alloff()
    ActiveThread.__init__(self)

  def alloff(self):
    self.redon = False
    self.greenon = False
    self.blueon = False
    self.pi.set_PWM_dutycycle(self.RED, 0)
    self.pi.set_PWM_dutycycle(self.BLUE, 0)
    self.pi.set_PWM_dutycycle(self.GREEN, 0)

  def lightUp(self, rVal, gVal, bVal):
    self.redOn = True
    self.greenOn = True
    self.blueOn = True
    self.pi.set_PWM_dutycycle(self.RED, rVal)
    self.pi.set_PWM_dutycycle(self.BLUE, gVal)
    self.pi.set_PWM_dutycycle(self.GREEN, bVal)   

  def _dispatch(self, message):
    print message
    if message[0] == "led_on":
      rVal, gVal, bVal = message[1]
      self.lightUp(rVal, gVal, bVal)
    elif message[0] == "led_off":
      self.alloff()

class PushButtonInterrupt(object):
  def __init__(self, commandcenter, inputport):
    self.inputport = inputport
    self.commandcenter = commandcenter

  def __enter__(self):
    if "debug" not in DEVICE:
      GPIO.setmode(GPIO.BCM)
      GPIO.setup(self.inputport, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
      print "Added event detect"
      GPIO.add_event_detect(
          self.inputport,
          GPIO.RISING,
          callback = self.signalreconnect,
          bouncetime=200)
    else:
      self.debugging = True
      self.add_keyb_event(self.signalreconnect)
    self.stop = False
    return self

  def waitkey(self, success):
    print "waiting for raw input"
    raw_input()
    if self.debugging:
      print "Button pressed"
      success()


  def add_keyb_event(self, callback):
    self.debugthread = Thread(target = self.waitkey, args = (callback,))
    self.debugthread.setDaemon(True)
    self.debugthread.start()
  
  def signalreconnect(self, channel):
    send(self.commandcenter, ["pushbutton", channel])
    if "debug" not in DEVICE:
      GPIO.add_event_detect(
          self.inputport,
          GPIO.FALLING,
          callback = self.signalreconnect,
          bouncetime=200)
    else:
      self.add_keyb_event(self.signalreconnect)

  def __exit__(self, type, value, traceback):
    if "debug" not in DEVICE:
      print "Stopping the detect"
      GPIO.remove_event_detect(self.inputport)
    else:
      self.debugging = False

class BluetoothConnectionCreator(ActiveThread):
  def __init__(
      self, commandcenter, filepath, adverttimeout, silenttimeout, portnum):
    self.shelvefile = shelve.open(filepath)
    self.lastknown = self.shelvefile.setdefault("last", None)
    self.shelvefile.sync()
    self.adverttimeout = adverttimeout
    self.silenttimeout = silenttimeout
    self.looping = False
    self.loopinglock = Lock()
    self.silent = self.lastknown != None
    self.silentlock = Lock()
    self.commandcenter = commandcenter
    self.connectionThread = Thread(target=self.make_connection)
    self.portnum = portnum
    ActiveThread.__init__(self)

  def _dispatch(self, message):
    if message[0] == "die":
      self.stop_poll()
    elif message[0] == "loud":
      self.loud_reconnect()
    elif message[0] == "start":
      self.connectionThread.setDaemon(True)
      self.connectionThread.start()

  def advertise(self, server_sock):
    advertise_service(server_sock,
          "SpeedLight", 
          service_classes = ["059c01eb-feaa-0e13-ffc4-f5d6f3be76d9"],
          profiles = [SERIAL_PORT_PROFILE],
          provider = "Fruitmill",
          description= "Use this while driving to Live long and Prosper.")

  def stop_poll(self):
    with self.loopinglock:
      self.looping = False
    self.connectionThread.join()
    
  def handshake(self, client_sock):
    try:
      readable, writable, excepts = select([client_sock], [], [], 5)
      if client_sock in readable:
        data = client_sock.recv(1024)
        h = uberhash(data)
        print "received: ", data, " sending: ", h
        client_sock.send(h + "\0")
        readable, writable, excepts = select([client_sock], [], [], 5)
        if client_sock in readable:
          data = client_sock.recv(1024)
          print "received: ", data, " expected: ", uberhash(h)
          if uberhash(h) == data:
            return True
          else:
            print "Failed 2"
        else:
          print "Failed 1"
    except Exception:
      print "Handshake failed."
    client_sock.close()
    return False
  
  def make_connection(self):
    server_sock = BluetoothSocket( RFCOMM )
    server_sock.setblocking(False)
    server_sock.bind(( " " , self.portnum))
    server_sock.listen(1)
    self.advertise(server_sock)
    print "advertising"
    with self.loopinglock:
      self.looping = True
    while self.looping:
      silent = self.silent
      timeout = self.silenttimeout
      readable, writable, excepts = select([server_sock], [], [], timeout)
      if server_sock in readable:
        client_sock, client_info = server_sock.accept()
        client_sock.setblocking(False)
        if silent:
          if client_info == self.lastknown:
            if self.handshake(client_sock):
              send(self.commandcenter, ["connected", client_sock])
          else:
            client_sock.send("Im paired for life! But you know, you could still press that button. You know you want to.")
            client_sock.close()
        else:
          if self.handshake(client_sock):
            send(self.commandcenter, ["connected", client_sock])
          self.shelvefile["last"] = client_info
          self.shelvefile.sync()
      if not silent and self.shelvefile["last"]:
        with self.silentlock:
          self.silent = True
    server_sock.close()

  def loud_reconnect(self):
    with self.silentlock:
      self.silent = False
    print "Loud reconnect"

class BluetoothCommunicator(ActiveThread):
  def __init__(self, commandcenter, connectionsize):
    self.client_sock = None
    self.client_sock_lock = Lock()
    self.established = False
    self.active = True
    self.connectionsize = connectionsize
    self.commandcenter = commandcenter
    self.transfer = Thread(target = self.get_and_transfer)
    ActiveThread.__init__(self)

  def _dispatch(self, message):
    if message[0] == "die":
      self.stop_working()
    elif message[0] == "start":
      self.transfer.setDaemon(True)
      self.transfer.start()
    elif message[0] == "connected":
      self.swap_sock(message[1])

  def swap_sock(self, client_sock):
    with self.client_sock_lock:
      old_sock = self.client_sock
      self.client_sock = client_sock
      self.established = True
    if old_sock:
      old_sock.close()

  def get_and_transfer(self):
    while self.active:
      if self.established and self.client_sock != None:
        print "established"
        with self.client_sock_lock:
          readable, writable, excepts = select([self.client_sock], [], [], 1)
          if self.client_sock in readable:
            print "reading data"
            try:
              data = self.client_sock.recv(self.connectionsize)
              if data:
                print "data received", data
                send(self.commandcenter, ["execute", data])
            except BluetoothError:
              print "Device closed the socket"
              self.established = False
              self.client_sock.close()
              self.client_sock = None
      time.sleep(0.01)
               
  def stop_working(self):
    self.active = False
    self.transfer.join()
    if self.established:
      self.client_sock.close()
      self.established = False
  

class CommandCenter(ActiveThread):
  def __init__(self, pushbuttonport):
    self.pushbuttonport = pushbuttonport
    self.blcomm = None
    self.blcreator = None
    self.LEDcon = None
    ActiveThread.__init__(self)

  def register(self, blcomm, blcreator, LEDcon):
    self.blcomm = blcomm
    self.blcreator = blcreator
    self.LEDcon = LEDcon

  def _dispatch(self, message):
    if message[0] == "die":
      send(self.blcomm, ["die"])
      send(self.blcreator, ["die"])
      send(self.LEDcon, ["die"])
    elif message[0] == "execute":
      data = json.loads(message[1])
      for command in data:
        if command == "die":
          send(self, ["die"])
        else:
          send(self.LEDcon, [command, data[command]])
    elif message[0] == "start":
      send(self.blcreator, ["start"])
      send(self.blcomm, ["start"])
    elif message[0] == "connected":
      send(self.blcomm, message)
    elif message[0] == "pushbutton":
      if message[1] == self.pushbuttonport:
        send(self.blcreator, ["loud"])


PUSHBUTTONPORT = 23
BLUE = 24
RED = 17
GREEN = 22
CONNECTIONSIZE = 1024
FILEPATH = "lastknown.shelve"
ADVERTTIMEOUT = 20
SILENTTIMEOUT = 1
PORTNUM = 3
commandcenter = CommandCenter(PUSHBUTTONPORT)
LEDcon = LEDController(RED, GREEN, BLUE)
blcreator = BluetoothConnectionCreator(
                commandcenter, FILEPATH, ADVERTTIMEOUT, SILENTTIMEOUT, PORTNUM)
blcomm = BluetoothCommunicator(commandcenter, CONNECTIONSIZE)
commandcenter.register(blcomm, blcreator, LEDcon)
stop = False
while not stop:
  try:
    with PushButtonInterrupt(commandcenter, PUSHBUTTONPORT) as pushb:
      send(commandcenter, ["start"])
      commandcenter.join()
  except KeyboardInterrupt:
    break
send(commandcenter, ["die"])
GPIO.cleanup()
#Ssudo bluetoothd --compat -n -d 5&
