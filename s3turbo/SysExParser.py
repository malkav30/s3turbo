import time, struct
from progress.bar import IncrementalBar

from s3turbo.MessagePrinter import MessagePrinter
from s3turbo.MSCEIMessage   import MSCEIMessage
from s3turbo.S3Turbo        import S3FunctionName
from s3turbo.Util           import checksum, conv7_8, noop, cancel, hexdump
from s3turbo.Util           import mktimestamp, list2str

class SysExParser(object):
    def __init__(self,send_func,debug=False):
        super(SysExParser,self).__init__()
        self.send_func  = send_func
        self.debug      = debug
        self.dump_file  = None
        self.dump_on    = False
        self.dump_ram   = False
        self.printer    = MessagePrinter(debug=self.debug)
        self.handlers   = {
            # FILE FUNCTIONS  FILE_F
            "F_DHDR":      self.handleFileDumpHeader,
            "F_DPKT":      self.handleFileDumpDataBlock,
            "DIR_HDR":     self.handleFileDumpHeader,
            "F_WAIT"     : noop,
            "F_CANCEL"   : cancel,
            "F_ERR"      : cancel,
            # DEVICE COMMAND  DEVICE_CMD
            "STAT_ANSWER": self.handleStatusAnswer,
            "DATA_HEADER": self.handleDirectoryAnswer,
            "DATA_DUMP"  : self.handleDataDump,
            "DIR_ANSWER" : self.handleDirectoryAnswer,
            "D_WAIT"     : noop,
            "D_ACK"      : noop,
            "D_CANCEL"   : cancel,
            "D_ERR"      : cancel,
        }

        self.dump_start = [ "F_DREQ", "DATA_REQUEST" ]
        self.dump_stop  = [ "F_CANCEL", "D_CANCEL"]

    def __del__(self):
        self.closeDumpFile()

    def createDumpFile(self,filename=None):
        if not filename:
            timestamp = time.strftime("%Y%m%d%H%M%S")
            filename="dump_%s.bin" % mktimestamp()
        self.dump_file = open(filename,"wb")
        
    def closeDumpFile(self):
        if not self.dump_file: return
        self.dump_file.close()
        self.dump_file = None

    def startDump(self,filename,size):
        if not self.dump_on: return
        self.dump_written = 0
        self.dump_size = size
        self.closeDumpFile()
        self.createDumpFile(filename)
        print "Dumping '%s'" % filename
        showsize = ' 0x%(index)06x' if self.dump_ram else ''
        self.bar = IncrementalBar(
            max=size,
            suffix = '%(percent)d%% [%(elapsed_td)s / %(eta_td)s]' + showsize)

    def stopDump(self):
        if not self.dump_on: return
        self.bar.finish()
        self.closeDumpFile()
        self.dump_on = False
        
    def dump(self,data,filename=None):
        if not self.dump_on: return
        if not self.dump_file:
            self.createDumpFile()
        if self.dump_written == self.dump_size:
            print "Discarding", len(data), "bytes, dump has ended"
        elif len(data) + self.dump_written > self.dump_size:
            discard = len(data) + self.dump_written - self.dump_size
            self.dump_file.write(bytearray(data[:-discard]))
            self.bar.next(self.dump_size-self.dump_written)
            self.dump_written = self.dump_size
            self.bar.finish()
            leftover = data[-discard:]
            for i in leftover:
                if i != 0:
                    print "Discarding non-NUL data:", hexdump(leftover)
                    break
        else:
            self.dump_file.write(bytearray(data))
            self.dump_written += len(data)
            self.bar.next(len(data))
        
    # FILE FUNCTIONS  FILE_F
    def handleFileDumpHeader(self,msg,timestamp):
        self.sendSysEx( MSCEIMessage(fromName="F_WAIT"),timestamp=timestamp+1)
        offset=17
        data = []
        for i in xrange(2):
            data += conv7_8(msg[offset:offset+8])
            offset += 8
        location = ''
        while msg[offset] != 0:
            location += chr(msg[offset])
            offset += 1
        offset+=1
        cc = msg[offset]
        cc_calc = checksum(msg[1:offset])
        if cc == cc_calc:
            filename = str(bytearray(msg[5:16])).strip()
            length = struct.unpack('>I',list2str(data[4:8]))[0]
            self.startDump(filename,length)
            self.dump(data[8:])
            self.sendSysEx( MSCEIMessage(fromName="F_ACK"),
                            timestamp=timestamp+2)
        else:
            self.sendSysEx( MSCEIMessage(fromName="F_NACK"),
                            timestamp=timestamp+2)
        return True
        
    def handleFileDumpDataBlock(self,msg,timestamp):
        self.sendSysEx( MSCEIMessage(fromName="F_WAIT"),timestamp=timestamp+1)
        noctets = msg[5]
        offset=6
        data = []
        for i in xrange(noctets):
            data += conv7_8(msg[offset:offset+8])
            offset += 8
        cc = msg[offset]
        cc_calc = checksum(msg[1:offset])
        if cc == cc_calc:
            self.dump(data)
            self.sendSysEx( MSCEIMessage(fromName="F_ACK"),
                            timestamp=timestamp+2)
        else:
            self.sendSysEx( MSCEIMessage(fromName="F_NACK"),
                            timestamp=timestamp+2)
        return True

    # DEVICE COMMAND  DEVICE_CMD
    def handleStatusAnswer(self,msg,timestamp):
        self.sendSysEx( MSCEIMessage(fromName="D_WAIT"),timestamp=timestamp+1)
        offset= 5 + 3*8
        cc = msg[offset]
        cc_calc = checksum(msg[1:offset])
        if cc == cc_calc:
            self.sendSysEx( MSCEIMessage(fromName="D_ACK"),
                            timestamp=timestamp+2)
            if self.dump_ram:
                self.dump_on = True
                self.startDump("ramdump_%s.bin" % mktimestamp(), 2097060)
                time.sleep(0.1)
                self.sendSysEx( MSCEIMessage(fromName="F_ACK"),
                                timestamp=timestamp+3)
                return True
        else:
            self.sendSysEx( MSCEIMessage(fromName="D_NACK"),
                            timestamp=timestamp+2)
        return False

    def handleDataDump(self,msg,timestamp):
        self.sendSysEx( MSCEIMessage(fromName="D_WAIT"))
        noctets = msg[5]
        offset=6
        data = []
        for i in xrange(noctets):
            data += conv7_8(msg[offset:offset+8])
            offset += 8
        cc = msg[offset]
        cc_calc = checksum(msg[1:offset])
        if cc == cc_calc:
            self.dump(data)
            self.sendSysEx( MSCEIMessage(fromName="D_ACK"),
                            timestamp=timestamp+2)
        else:
            self.sendSysEx( MSCEIMessage(fromName="D_NACK"),
                            timestamp=timestamp+2)
        return True

    def handleDirectoryAnswer(self,msg,timestamp):
        #time.sleep(0.1)
        self.sendSysEx( MSCEIMessage(fromName="D_WAIT"),timestamp=timestamp+1)
        offset = 8 + 11 + 1
        data = []
        for i in xrange(2):
            data += conv7_8(msg[offset:offset+8])
            offset += 8
        offset += 11
        cc = msg[offset]
        cc_calc = checksum(msg[1:offset])
        if cc == cc_calc:
            filename = str(bytearray(msg[8:19])).strip()
            length = struct.unpack('>I',list2str(data[4:8]))[0]
            self.startDump(filename,length)
            #time.sleep(0.1)
            self.sendSysEx( MSCEIMessage(fromName="D_ACK"),
                            timestamp=timestamp+2)
        else:
            self.sendSysEx( MSCEIMessage(fromName="D_NACK"),
                            timestamp=timestamp+2)
        return True
        
    def parse(self, msg, timestamp, acceptUnhandled=True):
        if msg[0] != 0xF0:
            print 'Non-sysex message'
            print [ hex(b) for b in msg ]
            print
            return acceptUnhandled

        fname = S3FunctionName(msg)
        if not fname:
            print "Unhandled message"
            print msg
            return acceptUnhandled
        
        if self.debug: print "Received", fname, "@", timestamp
        self.printer.handle(fname,msg)
        if fname in self.dump_stop: self.stopDump()
        handler = self.handlers.get(fname, None)
        if handler: return handler(msg,timestamp=timestamp)
        else:       print fname, [ hex(b) for b in msg ]

    def sendSysEx(self,msg,timestamp=0):
        if msg.name:
            fname = msg.name
        else:
            fname = S3FunctionName(msg.raw())
        if fname:
            if self.debug: print "Sending ", fname, "@", timestamp
            self.printer.handle(fname,msg)
            if fname in self.dump_start:
                self.dump_on = True
            elif fname == 'RAM_DUMP':
                self.dump_ram = True
        self.send_func( (timestamp,msg.raw()))
