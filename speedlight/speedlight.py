from bluetooth import *
from select import *
from threading import Thread, Lock
import shelve, time, pigpio, json
from Queue import Queue

import RPi.GPIO as GPIO

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
      self._dispatch(message)      if message[0] == "die":        self._stop = True
class LEDController(ActiveThread):
  def __init__(self, red, green, blue):
    self.BLUE = blue
    self.RED = red
    self.GREEN = green
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

  def _dispatch(self, message):
    print message

class PushButtonInterrupt(object):
  def __init__(self, commandcenter, inputport):
    self.inputport = inputport
    self.commandcenter = commandcenter

  def __enter__(self):
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(self.inputport, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    self.stop = False
    GPIO.add_event_detect(
        self.inputport,
        GPIO.FALLING,
        callback = self.signalreconnect,
        bouncetime=200)

  def signalreconnect(self):
    send(self.commandcenter, ["pushbutton", self.inputport])
    GPIO.add_event_detect(
        self.inputport,
        GPIO.FALLING,
        callback = self.signalreconnect,
        bouncetime=200)

  def __exit__(self, type, value, traceback):
    GPIO.remove_event_detect(channel)

class BluetoothConnectionCreator(ActiveThread):
  def __init__(
      self, commandcenter, filepath, adverttimeout, silenttimeout, portnum):
    self.shelvefile = shelve.open(filepath)
    self.lastknown = self.shelvefile.setdefault("last", None)
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
          service_classes = [SERIAL_PORT_CLASS],
          profiles = [SERIAL_PORT_PROFILE],
          provider = "Fruitmill",
          description= "Use this while driving to Live long and prosper.")

  def stop_poll(self):
    with self.loopinglock:
      self.looping = False
    self.connectionThread.join()
  
  def make_connection(self):
    server_sock = BluetoothSocket( RFCOMM )
    server_sock.setblocking(False)
    server_sock.bind(( " " , self.portnum))
    server_sock.listen(1)
    with self.loopinglock:
      self.looping = True
    while self.looping:
      silent = self.silent
      if not silent:
        self.advertise(server_sock)
      timeout = self.adverttimeout if not silent else self.silenttimeout
      readable, writable, excepts = select([server_sock], [], [], timeout)
      if server_sock in readable:
        client_sock, client_info = server_sock.accept()
        client_sock.setblocking(False)
        if silent:
          if client_info == self.lastknown:
            send(self.commandcenter, ["connected", client_sock])
          else:
            client_sock.close()
        else:
          send(self.commandcenter, ["connected", client_sock])
          self.shelvefile["last"] = client_info
      if not silent:
        stop_advertising(server_sock)
        with self.silentlock:
          self.silent = True
    server_sock.close()

  def loud_reconnect(self):
    with self.silentlock:
      self.silent = False

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
    old_sock.close()

  def get_and_transfer(self):
    while self.active:
      if self.established and self.client_sock != None:
        with self.client_sock_lock:
          readable, writable, excepts = select([self.client_sock], [], [], 1)
          if self.client_sock in readable:
            data = self.client_sock.recv(self.connectionsize)
            if data:
              send(self.commandcenter, ["execute", data])
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
      for command in data["commands"]:
        if command == "die":
          send(self, ["die"])
        else:
          send(self.LEDcon, [command["command"], command["value"]])
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
    send(commandcenter, ["start"])
    commandcenter.join()
  except KeyboardInterrupt:
    break
send(commandcenter, ["die"])
GPIO.cleanup()
#Ssudo bluetoothd --compat -n -d 5&