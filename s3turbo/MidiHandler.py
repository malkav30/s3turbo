import pypm, signal, os, time
from multiprocessing import Process, Pipe

class MidiHandler(object):
    INPUT=0
    OUTPUT=1
    
    def __init__(self):
        super(MidiHandler,self).__init__()
        self.procs   = []
        pypm.Initialize()
        
    def __del__(self):
        self.stop()
        pypm.Terminate()

    def initialize(self, indev=-1, outdev=-1, latency=10, msgfilter=[],
                   debug=False):
        self.indev     = indev
        self.outdev    = outdev
        self.latency   = latency
        self.msgfilter = msgfilter
        self.debug     = debug
        
        self.initInput()
        self.initOutput()

    def initInput(self):
        if self.indev < 0:
            self.print_dev(self.INPUT)
            self.indev = int(raw_input("Type input number: "))
        self.recv_conn, recv_conn = Pipe()
        self.recv_proc = Process(
            target=MidiHandler.recv_real,
            args=(recv_conn,self.indev,self.msgfilter,self.debug)
        )
        self.recv_proc.start()
        self.procs.append((self.recv_proc,self.recv_conn))

    def initOutput(self):
        if self.outdev < 0:
            self.print_dev(self.OUTPUT)
            self.outdev = int(raw_input("Type output number: "))
        self.send_conn, send_conn = Pipe()
        self.send_proc = Process(
            target=MidiHandler.send_real,
            args=(send_conn,self.outdev,self.latency,self.debug)
        )
        self.send_proc.start()
        self.procs.append((self.send_proc,self.send_conn))

    def stop(self):
        for proc, conn in self.procs:
            if proc.is_alive():
                conn.send((-1,[]))
                proc.join()

    def send(self, payload):
        self.send_conn.send(payload)

    def poll(self, timeout):
        return self.recv_conn.poll(timeout)

    def recv(self):
        return self.recv_conn.recv()

    @staticmethod
    def send_real(send_conn, outdev, latency, debug=False):
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        MidiOut = pypm.Output(outdev, latency)
        while True:
            try:
                timestamp, msg = send_conn.recv()
            except EOFError, e:
                break
            if timestamp < 0:
                break
            if not msg or len(msg) < 2:
                print "Malformed message", timestamp, [ hex(b) for b in msg ]
                continue

            # sysex
            if msg[0] == 0xF0 and msg[-1] == 0xF7:
                if debug:
                    print "Sending  SysEx:", timestamp, [ hex(b) for b in msg ]
                MidiOut.WriteSysEx( timestamp, msg)
            else:
                print "Trying to send non-sysex message"
                pass
        del MidiOut
        
    @staticmethod
    def recv_real(recv_conn, indev, msgfilter=[], debug=False):
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        MidiIn = pypm.Input(indev)
        # does not seem to work, leave at default (FILT_ACTIVE)
        #MidiIn.SetFilter(pypm.FILT_ACTIVE | pypm.FILT_CLOCK)
        bufsize=10
        sysex = []
        sysex_timestamp = None
        while True:
            try:
                if recv_conn.poll():
                    (timestamp, msg) = recv_conn.recv()
                    if timestamp < 0:
                        break
            except EOFError:
                break
            
            #while not MidiIn.Poll(): pass
            # sleep 1ms to keep CPU usage down
            time.sleep(1e-3)
            MidiData = MidiIn.Read(bufsize)
            nev = len(MidiData)
            for msg in MidiData:
                msgtype = msg[0][0]
                timestamp = msg[1]
                ignore = False
                for f in msgfilter:
                    for i in xrange(min(len(f),len(msg[0]))):
                        if f[i] != msg[0][i]:
                            break
                    else:
                        ignore = True
                if ignore:
                    continue

                if msgtype == 0xF0:
                    sysex = msg[0]
                    sysex_timestamp = timestamp
                elif sysex_timestamp == timestamp:
                    sysex += msg[0]
                    if 0xF7 in sysex:
                        sysex = sysex[:sysex.index(0xF7)+1]
                        if debug:
                            print "Received SysEx:", sysex_timestamp, \
                                [hex(b) for b in sysex ]
                        recv_conn.send( (sysex_timestamp, sysex))
                        sysex = []
                        sysex_timestamp = None
                else:
                    recv_conn.send( (timestamp, msg[0]))
        del MidiIn
                    
    def print_dev(self,InOrOut):
        for loop in range(pypm.CountDevices()):
            interf,name,inp,outp,opened = pypm.GetDeviceInfo(loop)
            if ((InOrOut == MidiHandler.INPUT) & (inp == 1) |
                (InOrOut == MidiHandler.OUTPUT) & (outp ==1)):
                print loop, name," ",
                if (inp == 1): print "(input) ",
                else: print "(output) ",
                if (opened == 1): print "(opened)"
                else: print "(unopened)"
        print
