##------------------------------------------
##--- Author: Fred
##--- on appel un serveur vocal et on traduit en texte une liste de codes recus
##------------------------------------------

from serial import Serial
import RPi.GPIO as IO, atexit, logging, sys
from time import sleep
from enum import IntEnum
from datetime import datetime

import threading
import atexit
import sys
import re
import wave
import os
import fcntl
import subprocess


RINGS_BEFORE_AUTO_ANSWER = 2 #Must be greater than 1
MODEM_RESPONSE_READ_TIMEOUT = 120  #Time in Seconds (Default 120 Seconds)
MODEM_NAME = 'SimCOM'    # Modem Manufacturer, For Ex: 'U.S. Robotics' if the 'lsusb' cmd output is similar to "Bus 001 Device 004: ID 0baf:0303 U.S. Robotics"
REC_VM_MAX_DURATION = 120  # Record Voice Mail Variables Time in Seconds
disable_modem_event_listener = True # Used in global event listener
##analog_modem = serial.Serial() # Global Modem Object
audio_file_name = ''



PORT="/dev/ttyS0"
BAUD=115200
GSM_ON=11
GSM_RESET=12
DATE_FMT='"%y/%m/%d,%H:%M:%S%z"'
CPIN_IS_OK=0
REPLY=""

APN="mmsbouygtel.com"
APN_USERNAME=""
APN_PASSWORD="" # Leave blank
pincode = 8743
BALANCE_USSD="*100#"

# Balance: *100*7#
# Remaining Credit: *100#
# Voicemail: 443 (costs 8p!)
# Text Delivery Receipt (start with): *0#
# Hide calling number: #31#

class ATResp(IntEnum):
	ErrorNoResponse=-1
	ErrorDifferentResponse=0
	OK=1

class SMSMessageFormat(IntEnum):
	PDU=0
	Text=1

class SMSTextMode(IntEnum):
	Hide=0
	Show=1

class SMSStatus(IntEnum):
	Unread=0
	Read=1
	Unsent=2
	Sent=3
	All=4

	@classmethod
	def fromStat(cls, stat):
		if stat=='"REC UNREAD"': return cls.Unread
		elif stat=='"REC READ"': return cls.Read
		elif stat=='"STO UNSENT"': return cls.Unsent
		elif stat=='"STO SENT"': return cls.Sent
		elif stat=='"ALL"': return cls.All

	@classmethod
	def toStat(cls, stat):
		if stat==cls.Unread: return "REC UNREAD"
		elif stat==cls.Read: return "REC READ"
		elif stat==cls.Unsent: return "STO UNSENT"
		elif stat==cls.Sent: return "STO SENT"
		elif stat==cls.All: return "ALL"

class RSSI(IntEnum):
	"""
	Received Signal Strength Indication as 'bars'.
	Interpretted form AT+CSQ return value as follows:

	ZeroBars: Return value=99 (unknown or not detectable)
	OneBar: Return value=0 (-115dBm or less)
	TwoBars: Return value=1 (-111dBm)
	ThreeBars: Return value=2...30 (-110 to -54dBm)
	FourBars: Return value=31 (-52dBm or greater)
	"""

	ZeroBars=0
	OneBar=1
	TwoBars=2
	ThreeBars=3
	FourBars=4

	@classmethod
	def fromCSQ(cls, csq):
		csq=int(csq)
		if csq==99: return cls.ZeroBars
		elif csq==0: return cls.OneBar
		elif csq==1: return cls.TwoBars
		elif 2<=csq<=30: return cls.ThreeBars
		elif csq==31: return cls.FourBars

class NetworkStatus(IntEnum):
	NotRegistered=0
	RegisteredHome=1
	Searching=2
	Denied=3
	Unknown=4
	RegisteredRoaming=5

@atexit.register
def cleanup(): IO.cleanup()

class AT_SIMCOM(object):
	def __init__(self, port, baud, logger=None, loglevel=logging.WARNING):
		self._port=port
		self._baud=baud

		self._ready=False
		self._serial=None

		if logger: self._logger=logger
		else:
			self._logger=logging.getLogger("AT_SIMCOM")
			handler=logging.StreamHandler(sys.stdout)
			handler.setFormatter(logging.Formatter("%(asctime)s : %(levelname)s -> %(message)s"))
			self._logger.addHandler(handler)
			self._logger.setLevel(loglevel)

	def setup(self):
		"""
		Setup the IO to control the power and reset inputs and the serial port.
		"""
		self._logger.debug("Setup")
		IO.setmode(IO.BOARD)
		IO.setup(GSM_ON, IO.OUT, initial=IO.LOW)
		IO.setup(GSM_RESET, IO.OUT, initial=IO.LOW)
		self._serial=Serial(self._port, self._baud)

	def reset(self):
		"""
		Reset (turn on) the SIM800 module by taking the power line for >1s
		and then wait 5s for the module to boot.
		"""
		self._logger.debug("Reset (duration ~6.2s)")
		IO.output(GSM_ON, IO.HIGH)
		sleep(1.2)
		IO.output(GSM_ON, IO.LOW)
		sleep(5.)

	def sendATCmd_WaitResp(self, cmd, response, timeout=.5, interByteTimeout=.1, attempts=1, addCR=False):
		"""
		This function is designed to check for simple one line responses, e.g. 'OK'.
		"""
		self._logger.debug("Send AT Command: {}".format(cmd))
		self._serial.timeout=timeout
		self._serial.inter_byte_timeout=interByteTimeout

		status=ATResp.ErrorNoResponse
		for i in range(attempts):
			bcmd=cmd.encode('utf-8')+b'\r'
			if addCR: bcmd+=b'\n'

			self._logger.debug("Attempt {}, ({})".format(i+1, bcmd))
			#self._serial.write(cmd.encode('utf-8')+b'\r')
			self._serial.write(bcmd)
			self._serial.flush()

			lines=self._serial.readlines()
			lines=[l.decode('utf-8').strip() for l in lines]
			lines=[l for l in lines if len(l) and not l.isspace()]
			self._logger.debug("Lines: {}".format(lines))
			if len(lines)<1: continue
			line=lines[-1]
			self._logger.debug("Line: {}".format(line))

			if not len(line) or line.isspace(): continue
			elif line==response: return ATResp.OK
			else: return ATResp.ErrorDifferentResponse
		return status

	def sendATCmd_WaitReturn_Resp(self, cmd, response, timeout=.5, interByteTimeout=.1):
		"""
		This function is designed to return data and check for a final response, e.g. 'OK'
		"""
		self._logger.debug("Send AT Command: {}".format(cmd))
		self._serial.timeout=timeout
		self._serial.inter_byte_timeout=interByteTimeout

		self._serial.write(cmd.encode('utf-8')+b'\r')
		self._serial.flush()
		lines=self._serial.readlines()
		for n in range(len(lines)):
			try: lines[n]=lines[n].decode('utf-8').strip()
			except UnicodeDecodeError: lines[n]=lines[n].decode('latin1').strip()

		lines=[l for l in lines if len(l) and not l.isspace()]
		self._logger.debug("Lines: {}".format(lines))

		if not len(lines): return (ATResp.ErrorNoResponse, None)

		_response=lines.pop(-1)
		self._logger.debug("Response: {}".format(_response))
		if not len(_response) or _response.isspace(): return (ATResp.ErrorNoResponse, None)
		elif response==_response: return (ATResp.OK, lines)
		return (ATResp.ErrorDifferentResponse, None)

	def parseReply(self, data, beginning, divider=',', index=0):
		"""
		Parse an AT response line by checking the reply starts with the expected prefix,
		splitting the reply into its parts by the specified divider and then return the
		element of the response specified by index.
		"""
		self._logger.debug("Parse Reply: {}, {}, {}, {}".format(data, beginning, divider, index))
		if not data.startswith(beginning): return False, None
		data=data.replace(beginning,"")
		data=data.split(divider)
		try: return True,data[index]
		except IndexError: return False, None

	def getSingleResponse(self, cmd, response, beginning, divider=",", index=0, timeout=.5, interByteTimeout=.1):
		"""
		Run a command, get a single line response and the parse using the
		specified parameters.
		"""
		status,data=self.sendATCmd_WaitReturn_Resp(cmd,response,timeout=timeout,interByteTimeout=interByteTimeout)
		if status!=ATResp.OK: return None
		if len(data)!=1: return None
		ok,data=self.parseReply(data[0], beginning, divider, index)
		if not ok: return None
		return data

	def turnOn(self):
		"""
		Check to see if the module is on, if so return. If not, attempt to
		reset the module and then check that it is responding.
		"""
		self._logger.debug("Turn On")
		for i in range(2):
			status=self.sendATCmd_WaitResp("AT", "OK", attempts=5)
			if status==ATResp.OK:
				self._logger.debug("GSM module ready.")
				self._ready=True
				return True
			elif status==ATResp.ErrorDifferentResponse:
				self._logger.debug("GSM module returned invalid response, check baud rate?")
			elif i==0:
				self._logger.debug("GSM module is not responding, resetting...")
				self.reset()
			else: self._logger.error("GSM module failed to respond after reset!")
		return False

	def setEchoOff(self):
		"""
		Switch off command echoing to simply response parsing.
		"""
		self._logger.debug("Set Echo Off")
		self.sendATCmd_WaitResp("ATE0", "OK")
		status=self.sendATCmd_WaitResp("ATE0", "OK")
		return status==ATResp.OK
	### FRED
	def setATH(self):
		self._logger.debug("Set ATH")
		status=self.sendATCmd_WaitResp("ATH","OK")
		return status==ATResp.OK

	def setATF(self):
		self._logger.debug("Set AT&F")
		status=self.sendATCmd_WaitResp("AT&F","OK")
		return status==ATResp.OK

	def setATW(self):
		self._logger.debug("Set AT&W")
		status=self.sendATCmd_WaitResp("AT&W","OK")
		return status==ATResp.OK

	def setATZ(self):
			self._logger.debug("Set ATZ")
			status=self.sendATCmd_WaitResp("ATZ","OK")
			return status==ATResp.OK

	def setExtendedError(self):
		"""
		Set verbose Error mode 2
		"""
		self._logger.debug("Set Extended Error : {}".format(2))
		status=self.sendATCmd_WaitResp("AT+CMEE={}".format(2),"OK")
		return status==ATResp.OK

	def ForcePinCode(self):
		"""
		Force pin Code
		"""
		self._logger.debug("“AT CFUN=1,1” reset module purposely")
		status=self.sendATCmd_WaitResp("AT+CFUN=1,1","OK")

		if (status==ATResp.OK):
			print ("waiting PINCODE time ")
			sleep(5)
			self._logger.debug("Set Pin Code")
			status=self.sendATCmd_WaitResp("AT+CPIN=8743","+CPIN: READY")
			CPIN_IS_OK = 1
			return status==ATResp.OK
		else:
			CPIN_IS_OK = 0
			return status==ATResp.ErrorDifferentResponse

	def setCLIP(self):
		self._logger.debug("Set CLIP : {}".format(1))
		status=self.sendATCmd_WaitResp("AT+CLIP={}".format(1),"OK")
		#status=self.sendATCmd_WaitReturn_Resp("AT+CLIP","OK")
		return status==ATResp.OK

	def setDDET(self):
		self._logger.debug("Set DDET : {}".format(1))
		status=self.sendATCmd_WaitResp("AT+DDET={}".format(1),"OK")
		#status=self.sendATCmd_WaitReturn_Resp("AT+DDET=1","OK")
		return status==ATResp.OK

	def setATS0(self):
		self._logger.debug("Set ATS0 : {}".format(0))
		status=self.sendATCmd_WaitResp("ATS0={}".format(0),"OK")
		return status==ATResp.OK
	### FRED

	def getLastError(self):
		"""
		Get readon for last error
		"""
		self._logger.debug("Get Last Error")
		error=self.getSingleResponse("AT+CEER","OK","+CME: ")
		return error

	def getIMEI(self):
		"""
		Get the IMEI number of the module
		"""
		self._logger.debug("Get International Mobile Equipment Identity (IMEI)")
		status,imei=self.sendATCmd_WaitReturn_Resp("AT+GSN","OK")
		if status==ATResp.OK and len(imei)==1: return imei[0]
		return None

	def getVersion(self):
		"""
		Get the module firmware version.
		"""
		self._logger.debug("Get TA Revision Identification of Software Release")
		revision=self.getSingleResponse("AT+CGMR","OK","Revision",divider=":",index=1)
		return revision

	def getSIMCCID(self):
		"""
		The the SIM ICCID.
		"""
		self._logger.debug("Get SIM Integrated Circuit Card Identifier (ICCID)")
		status,ccid=self.sendATCmd_WaitReturn_Resp("AT+CCID","OK")
		if status==ATResp.OK and len(ccid)==1: return ccid[0]
		return None

	def getNetworkStatus(self):
		"""
		Get the current network connection status.
		"""
		self._logger.debug("Get Network Status")
		status=self.getSingleResponse("AT+CREG?","OK","+CREG: ",index=1)
		if status is None: return status
		return NetworkStatus(int(status))

	def getRSSI(self):
		"""
		Get the current signal strength in 'bars'
		"""
		self._logger.debug("Get Received Signal Strength Indication (RSSI)")
		csq=self.getSingleResponse("AT+CSQ","OK","+CSQ: ")
		if csq is None: return csq
		return RSSI.fromCSQ(csq)

	def enableNetworkTimeSync(self, enable):
		self._logger.debug("Enable network time synchronisation")
		status=self.sendATCmd_WaitResp("AT+CLTS={}".format(int(enable)),"OK")
		return status==ATResp.OK

	def getTime(self):
		"""
		Get the current time
		"""
		self._logger.debug("Get the current time")
		time=self.getSingleResponse("AT+CCLK?","OK","+CCLK: ", divider="'")
		if time is None: return time
		return datetime.strptime(time[:-1]+'00"', DATE_FMT)

	def setTime(self, time):
		"""
		"""
		self._logger.debug("Set the current time: {}".format(time))
		time=datetime.strftime(time, DATE_FMT)
		if time[-4]!="+": time=time[:-1]+'+00"'
		status=self.sendATCmd_WaitResp("AT+CCLK={}".format(time),"OK")
		return status==ATResp.OK

	def setSMSMessageFormat(self, format):
		"""
		Set the SMS message format either as PDU or text.
		"""
		status=self.sendATCmd_WaitResp("AT+CMGF={}".format(format), "OK")
		return status==ATResp.OK

	def setSMSTextMode(self, mode):
		status=self.sendATCmd_WaitResp("AT+CSDH={}".format(mode), "OK")
		return status==ATResp.OK

	def getNumSMS(self):
		"""
		Get the number of SMS on SIM card
		"""
		self._logger.debug("Get Number of SMS")
		if not self.setSMSMessageFormat(SMSMessageFormat.Text):
			self._logger.error("Failed to set SMS Message Format!")
			return False

		if not self.setSMSTextMode(SMSTextMode.Show):
			self._logger.error("Failed to set SMS Text Mode!")
			return False

		num=self.getSingleResponse('AT+CPMS?', "OK", "+CPMS: ", divider='"SM",', index=1)
		if num is None: return num
		n,t,*_=num.split(',')
		return int(n),int(t)

	def readSMS(self, number):
		"""
		Returns status, phone number, date/time and message in location specified by 'number'.
		"""
		self._logger.debug("Read SMS: {}".format(number))
		if not self.setSMSMessageFormat(SMSMessageFormat.Text):
			self._logger.error("Failed to set SMS Message Format!")
			return None

		if not self.setSMSTextMode(SMSTextMode.Show):
			self._logger.error("Failed to set SMS Text Mode!")
			return None

		status,(params,msg)=self.sendATCmd_WaitReturn_Resp("AT+CMGR={}".format(number),"OK")
		if status!=ATResp.OK or not params.startswith("+CMGR: "): return None

		# stat   : message status = "REC UNREAD", "REC READ", "STO UNSENT", "STO SENT", "ALL"
		# oa     : originating address
		# alpha  : string of "oa" or "da"
		# scts   : service center timestamp "YY/MM/DD,HH:MM:SS+ZZ"
		# tooa   : originating address type
		# fo     :
		# pid    : protocol ID
		# dcs    : data coding scheme
		# sca    :
		# tosca  :
		# length : length of the message body
		stat,oa,alpha,scts1,scts2,tooa,fo,pid,dcs,sca,tosca,length=params[7:].split(',')

		scts=scts1+','+scts2
		tz=scts[-2:]
		scts=scts[:-1]+'00"'
		scts=datetime.strptime(scts, DATE_FMT)
		return SMSStatus.fromStat(stat),oa[1:-1],scts,msg

	def readAllSMS(self, status=SMSStatus.All):
		self._logger.debug("Read All SMS")
		if not self.setSMSMessageFormat(SMSMessageFormat.Text):
			self._logger.error("Failed to set SMS Message Format!")
			return None

		if not self.setSMSTextMode(SMSTextMode.Show):
			self._logger.error("Failed to set SMS Text Mode!")
			return None

		status,msgs=self.sendATCmd_WaitReturn_Resp('AT+CMGL="{}"'.format(SMSStatus.toStat(status)), "OK")
		if status!=ATResp.OK or not msgs[0].startswith("+CMGL: ") or len(msgs)%2!=0: return None

		formatted=[]
		for n in range(0, len(msgs), 2):
			params,msg=msgs[n:n+2]
			if n==0: params=params[7:]
			loc,stat,oa,alpha,scts1,scts2,tooa,fo,pid,dcs,sca,tosca,length=params.split(',')
			scts=scts1+','+scts2
			tz=scts[-2:]
			scts=scts[:-1]+'00"'
			scts=datetime.strptime(scts, DATE_FMT)
			formatted.append((loc,SMSStatus.fromStat(stat),oa[1:-1],scts,msg))
		return formatted

	def deleteSMS(self, number):
		"""
		Delete the SMS in location specified by 'number'.
		"""
		self._logger.debug("Delete SMS: {}".format(number))
		if not self.setSMSMessageFormat(SMSMessageFormat.Text):
			self._logger.error("Failed to set SMS Message Format!")
			return False
		status=self.sendATCmd_WaitResp("AT+CMGD={:03d}".format(number), "OK")
		return status==ATResp.OK

	def sendSMS(self, phoneNumber, msg):
		"""
		Send the specified message text to the provided phone number.
		"""
		self._logger.debug("Send SMS: {} '{}'".format(phoneNumber, msg))
		if not self.setSMSMessageFormat(SMSMessageFormat.Text):
			self._logger.error("Failed to set SMS Message Format!")
			return False

		status=self.sendATCmd_WaitResp('AT+CMGS="{}"'.format(phoneNumber), ">", addCR=True)
		if status!=ATResp.OK:
			self._logger.error("Failed to send CMGS command part 1! {}".format(status))
			return False

		cmgs=self.getSingleResponse(msg+"\r\n\x1a", "OK", "+", divider=":", timeout=11., interByteTimeout=1.2)
		return cmgs=="CMGS"

	def sendUSSD(self, ussd):
		"""
		Send Unstructured Supplementary Service Data message
		"""
		self._logger.debug("Send USSD: {}".format(ussd))
		reply=self.getSingleResponse('AT+CUSD=1,"{}"'.format(ussd), "OK", "+CUSD: ", index=1, timeout=11., interByteTimeout=1.2)
		return reply

#=================================================================
# Modem Init
#=================================================================
def initialization_modem():
		s=AT_SIMCOM(PORT,BAUD,loglevel=logging.DEBUG)
		s.setup()
		if not s.turnOn(): exit(1)
		if not s.setEchoOff(): exit(1)
		if not s.setATH(): exit(1)
		if not s.setATF(): exit(1)
		if not s.setATW(): exit(1)
		if not s.setATZ(): exit(1)
		if not s.setExtendedError(): exit(1)
		if not s.ForcePinCode(): exit(1)
		if not s.setCLIP(): exit(1)
		if not s.setDDET(): exit(1)
		if not s.setATS0(): exit(1)
#=================================================================

#=================================================================
# Read DTMF Digits
#=================================================================
def dtmf_digits(modem_data):
	digits = ""
	digit_list = re.findall('/(.+?)~', modem_data)
	for d in digit_list:
		digits= digits + d[0]
	return digits
#=================================================================

#=================================================================
# Record wav file (Voice Msg/Mail)
#=================================================================
def record_audio():
	print ("Record Audio Msg - Start")

	# Enter Voice Mode
	if not exec_AT_cmd("AT","OK"):#if not exec_AT_cmd("AT+FCLASS=8","OK"):
		print ("Error: Failed to put modem into voice mode.")
		return

	# Set speaker volume to normal
	if not exec_AT_cmd("AT+VGT=128","OK"):
		print ("Error: Failed to set speaker volume to normal.")
		return

	# Compression Method and Sampling Rate Specifications
	# Compression Method: 8-bit linear / Sampling Rate: 8000MHz
	if not exec_AT_cmd("AT+VSM=128,8000","OK"):
		print ("Error: Failed to set compression method and sampling rate specifications.")
		return

	# Disables silence detection (Value: 0)
	if not exec_AT_cmd("AT+VSD=128,0","OK"):
		print ("Error: Failed to disable silence detection.")
		return

	# Put modem into TAD Mode
	if not exec_AT_cmd("AT+VLS=1","OK"):
		print ("Error: Unable put modem into TAD mode.")
		return

	# Enable silence detection.
	# Select normal silence detection sensitivity
	# and a silence detection interval of 5 s.
	if not exec_AT_cmd("AT+VSD=128,50","OK"):
		print ("Error: Failed tp enable silence detection.")
		return

	# Play beep.
	if not exec_AT_cmd("AT+VTS=[933,900,100]","OK"):
		print ("Error: Failed to play 1.2 second beep.")
		#return

	# Select voice receive mode
	if not exec_AT_cmd("AT+VRX","CONNECT"):
		print ("Error: Unable put modem into voice receive mode.")
		return

	# Record Audio File

	global disable_modem_event_listener
	disable_modem_event_listener = True


	# Set the auto timeout interval
	start_time = datetime.now()
	CHUNK = 1024
	audio_frames = []

	while 1:
		# Read audio data from the Modem
		##audio_data = analog_modem.read(CHUNK)
		audio_data = self._serial.read(CHUNK)

		# Check if <DLE>b is in the stream
		if ((chr(16)+chr(98)) in audio_data):
			print ("Busy Tone... Call will be disconnected.")
			break

		# Check if <DLE>s is in the stream
		if ((chr(16)+chr(115)) in audio_data):
			print ("Silence Detected... Call will be disconnected.")
			break

		# Check if <DLE><ETX> is in the stream
		if (("<DLE><ETX>").encode() in audio_data):
			print ("<DLE><ETX> Char Recieved... Call will be disconnected.")
			break

		# Timeout
		elif ((datetime.now()-start_time).seconds) > REC_VM_MAX_DURATION:
			print ("Timeout - Max recording limit reached.")
			break

		# Add Audio Data to Audio Buffer
		audio_frames.append(audio_data)

	global audio_file_name

	# Save the Audio into a .wav file
	wf = wave.open(audio_file_name, 'wb')
	wf.setnchannels(1)
	wf.setsampwidth(1)
	wf.setframerate(8000)
	wf.writeframes(b''.join(audio_frames))
	wf.close()

	# Reset Audio File Name
	audio_file_name = ''


	# Send End of Voice Recieve state by passing "<DLE>!"
	if not exec_AT_cmd((chr(16)+chr(33)),"OK"):
		print ("Error: Unable to signal end of voice receive state")

	# Hangup the Call
	if not exec_AT_cmd("ATH","OK"):
		print ("Error: Unable to hang-up the call")

	# Enable global event listener
	disable_modem_event_listener = False

	print ("Record Audio Msg - END")
	return
#=================================================================

#=================================================================
# Data Listener
#=================================================================
def read_data():

	global disable_modem_event_listener
	ring_data = ""

	while 1:

		if not disable_modem_event_listener:
			#modem_data = analog_modem.readline()
			modem_data = self._serial.readline()



			if modem_data != "":
				print (modem_data)

				# Check if <DLE>b is in the stream
				if (chr(16)+chr(98)) in modem_data:
					#Terminate the call
					if not exec_AT_cmd("ATH"):
						print ("Error: Busy Tone - Failed to terminate the call")
						print ("Trying to revoer the serial port")
						recover_from_error()
					else:
						print ("Busy Tone: Call Terminated")

				# Check if <DLE>s is in the stream
				if (chr(16)+chr(115)) == modem_data:
					#Terminate the call
					if not exec_AT_cmd("ATH"):
						print ("Error: Silence - Failed to terminate the call")
						print ("Trying to revoer the serial port")
						recover_from_error()
					else:
						print ("Silence: Call Terminated")


				if ("-s".encode() in modem_data) or (("<DLE>-s").encode() in modem_data):
					print ("silence found during recording")
					#analog_modem.write(("<DLE>-!" + "\r").encode())
					self._serial.write(("<DLE>-!" + "\r").encode())




				if ("RING" in modem_data) or ("DATE" in modem_data) or ("TIME" in modem_data) or ("NMBR" in modem_data):
					global audio_file_name
					if ("NMBR" in modem_data):
						from_phone = (modem_data[5:]).strip()
					if ("DATE" in modem_data):
						call_date =  (modem_data[5:]).strip()
					if ("TIME" in modem_data):
						call_time =  (modem_data[5:]).strip()
					if "RING" in modem_data.strip(chr(16)):
						ring_data = ring_data + modem_data
						ring_count = ring_data.count("RING")
						if ring_count == 1:
							pass
						elif ring_count == RINGS_BEFORE_AUTO_ANSWER:
							ring_data = ""
							audio_file_name = from_phone + "_" + call_date + "_" + call_time + "_" + str(datetime.strftime(datetime.now(),"%S")) + ".wav"
							from_phone = ''
							call_date = ''
							call_time = ''

							record_audio()
#=================================================================



if __name__=="__main__":
	try:
		initialization_modem()
	except Exception as e:
		print(e)
		initialization_modem()

	read_data() # Monitoring