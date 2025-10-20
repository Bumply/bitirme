import serial
import serial.tools.list_ports
import time

class CommManager(object):
    ser = None
    obstacleDetected = False
    finderEntryTime = 0   
    log_to_console = False 
    __homing = False
    
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = super(CommManager, cls).__new__(cls)
        return cls.instance
        
    def start(self):
        port = self.findCOMPort()
        if port is None or port == "None":
            self.ser = None
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.1)
            time.sleep(2)

        except:
            print('Failed to connect to port ' + port)
        finally:
            if self.ser is not None and port is not None:
                print('Connected to port ' + port)
            elif port is not None:
                print("Failed to connect to port: " + port)
            else:
                print("Failed to connect to any port")

    def __sendValues(self, speed, position):
        txMsg = "S:" + str(speed) + ",P:" + str(position) + "\n"
        self.ser.write(txMsg.encode(encoding='ascii'))
        
    def home(self):
        self.__homing = True
        self.ser.write("Home\n".encode(encoding='ascii'))

    def findCOMPort(self):
        ports = serial.tools.list_ports.comports(include_links=False)
        self.finderEntryTime = time.time()
        for port in ports:
            print('Found port ' + port.device)
            ser = None
            
            if (time.time() - self.finderEntryTime > 25):
                    print("Timeout waiting for port: " + port.device)
                    self.finderEntryTime = time.time()
                    continue
            
            try:
                ser = serial.Serial(port.device, 115200, timeout=0.2, write_timeout=1)
                time.sleep(2)
            except:
                print('Failed to open port ' + port.device)
                continue
            if ser is not None:
                chkMsg = "CHK\n"
                for _ in range(2):
                    try:
                        ser.write(chkMsg.encode("ascii"))
                    except:
                        print("Failed to write to port " + port.device)
                        break
                    time.sleep(0.01)
                    reply = ser.read_until(b"\n")
                    if reply.decode("ascii") == "OK\n":
                        ser.close()
                        print('COM Port Selected: ' + port.device)
                        return port.device
                    
                    elif reply.decode("ascii") == "":
                        print("No Reply from Device at " + port.device)
                        continue
                    else:
                        continue
        return None
    
    def eventLoop(self, pSpeed, pPosition):
        
        if (self.ser.port is None):
            return
        
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        
        rxMsg = ""
        
        '''        rxMsg = self.ser.read_until(b'\n').decode(encoding='ascii')
        if (rxMsg == "OD\n"):
                self.obstacleDetected = True

        elif (rxMsg == "OC\n"):
            self.obstacleDetected = False
            
        '''
            
        speed = pSpeed * -1 if pSpeed < 0 else 0

        if not self.__homing:
            self.__sendValues(speed=speed, position=pPosition)
        else:
            time.sleep(3)
            self.__homing = False
        
        if self.log_to_console:
            print("Sent: " + "S:" + str(speed) + ",P:" + str(pPosition))
            print("Received: " + rxMsg + "\n")