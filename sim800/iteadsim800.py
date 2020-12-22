from time import sleep

try:
    import RPi.GPIO as IO, atexit, logging, sys
except ImportError:
    raise ImportError( "Couldn't import RPi.GPIO. Installing it with pip could work: `pip install RPi.GPIO`" )

from sim800 import SIM800, NetworkStatus


GSM_ON=11
GSM_RESET=12
#PORT="/dev/ttyS0"
PORT="/dev/ttyAMA0"     # this port is right for RPi 3B+
BAUD=9600              # ITead's specs say this...
#BAUD=115200             # .. but this works too :)

BALANCE_USSD="*100#"


# Balance: *100*7#
# Remaining Credit: *100#
# Voicemail: 443 (costs 8p!)
# Text Delivery Receipt (start with): *0#
# Hide calling number: #31#


@atexit.register
def cleanup():
    IO.cleanup()


class IteadSIM800( SIM800 ):

    def __init__( self, port=PORT, baud=BAUD, logger=None, loglevel=logging.WARNING ):

        # TODO: autodetect port

        super( IteadSIM800, self ).__init__(
            port,
            baud,
            logger = logger,
            loglevel = loglevel 
        )


    def startup( self ):
        self.setup()
        if not self.turnOn(): exit(1)
        if not self.setEchoOff(): exit(1)


    def setup( self ):
        """
        Setup the IO to control the power and reset inputs and the serial port.
        """
        IO.setmode(IO.BOARD)
        IO.setup(GSM_ON, IO.OUT, initial=IO.LOW)
        IO.setup(GSM_RESET, IO.OUT, initial=IO.LOW)
        super( IteadSIM800, self ).setup()
    

    def reset( self ):
        """
        Reset (turn on) the SIM800 module by taking the power line for >1s
        and then wait 5s for the module to boot.
        """
        self._logger.debug("Reset (duration ~6.2s)")
        IO.output(GSM_ON, IO.HIGH)
        sleep(1.2)
        IO.output(GSM_ON, IO.LOW)
        sleep(5.)
        super( IteadSIM800, self ).reset()


if __name__=="__main__":
    s = IteadSIM800( PORT,BAUD,loglevel=logging.DEBUG )
    s.setup()
    if not s.turnOn(): exit(1)
    if not s.setEchoOff(): exit(1)
    print("Good to go!")
    print(s.getIMEI())
    print(s.getVersion())
    print(s.getSIMCCID())
    #print(s.getLastError())
    ns=s.getNetworkStatus()
    print(ns)
    if ns not in (NetworkStatus.RegisteredHome, NetworkStatus.RegisteredRoaming):
        exit(1)
    print(s.getRSSI())
    #print(s.enableNetworkTimeSync(True))
    # print(s.getTime())
    # print(s.setTime(datetime.now()))
    # print(s.getTime())
    # print(s.sendSMS("+441234567890", "Hello World!"))
    # print(s.sendSMS("150", "NUMBER")) # gets this phone's number on EE in the UK
    # print(s.sendUSSD(BALANCE_USSD))
    #print(s.getLastError())
    n, t = s.getNumSMS()
    print(s.getNumSMS())
    if n > 0:
        for i in range(1,n):
            print( s.readSMS(i) )
    #print(s.deleteSMS(1))
    #print(s.readAllSMS())
