##--------------------
##--- Author: Pradeep Singh
##--- Blog: https://iotbytes.wordpress.com/
##--- Date: 1st Dec 2017
##--- Version: 1.0
##--- Python Ver: 2.7
##--- Description: This python code will find the COM port associated with an analog Modem connected with Raspberry Pi
##--------------------


import serial
from datetime import datetime
import subprocess


# Global Modem Object
analog_modem = serial.Serial()
#Time in Seconds (Default 120 Seconds)
MODEM_RESPONSE_READ_TIMEOUT = 10
# Modem Manufacturer,
MODEM_NAME = 'U.S'


#==========================
# Set COM Port settings
#==========================
def set_COM_port_settings(com_port):
	analog_modem.port = com_port
	analog_modem.baudrate = 9600
	analog_modem.bytesize = serial.EIGHTBITS 	#number of bits per bytes
	analog_modem.parity = serial.PARITY_NONE 	#set parity check: no parity
	analog_modem.stopbits = serial.STOPBITS_ONE #number of stop bits
	analog_modem.timeout = 3            		#non-block read
	analog_modem.xonxoff = False     			#disable software flow control
	analog_modem.rtscts = False     			#disable hardware (RTS/CTS) flow control
	analog_modem.dsrdtr = False      			#disable hardware (DSR/DTR) flow control
	analog_modem.writeTimeout = 3     			#timeout for write
#==========================


#==========================
# Detect Modem COM Port
#==========================
def detect_COM_port():

	# List all the Serial COM Ports on Raspberry Pi
	proc = subprocess.Popen(['ls /dev/tty[A-Za-z]*'], shell=True, stdout=subprocess.PIPE)
	com_ports = proc.communicate()[0].decode("utf-8")
	com_ports_list = com_ports.split('\n')

	# Find the right port associated with the Voice Modem
	for com_port in com_ports_list:
		if 'ttyS0' in com_port:
			#Try to open the COM Port and execute AT Command
			try:
				# Set the COM Port Settings
				set_COM_port_settings(com_port)
				#analog_modem.open()
			except:
				print ("Unable to open COM Port: " + com_port)
				pass
			else:
				#Try to put Modem in Voice Mode
				if not exec_AT_cmd("AT", "OK"):
					print ("Error: Failed to put modem into voice mode.")
					#if analog_modem.isOpen():
					#	analog_modem.close()
				else:
					# Found the COM Port exit the loop
					print ("Analog Modem COM Port is: " + com_port)
					analog_modem.flushInput()
					analog_modem.flushOutput()
					analog_modem.close()
					break
#==========================

#==========================
# Execute AT Commands at the Modem
#==========================
def exec_AT_cmd(modem_AT_cmd, expected_response="OK"):
	try:
		# Send command to the Modem
		#analog_modem.write((modem_AT_cmd + "\r").encode())
		analog_modem.write('AT') #working in Python3.7

		# Read Modem response
		execution_status = read_AT_cmd_response(expected_response)
		disable_modem_event_listener = False
		# Return command execution status
		return execution_status

	except:
		print ("Error: Failed to execute the command")
		return False
#==========================

#==========================
# Read AT Command Response from the Modem
#==========================
def read_AT_cmd_response(expected_response="OK"):

	# Set the auto timeout interval
	start_time = datetime.now()

	try:
		while 1:
			# Read Modem Data on Serial Rx Pin
			modem_response = analog_modem.readline()
			print (modem_response)
			# Recieved expected Response
			if expected_response == modem_response.strip(' \t\n\r' + chr(16)):
				return True
			# Failed to execute the command successfully
			elif "ERROR" in modem_response.strip(' \t\n\r' + chr(16)):
				return False
			# Timeout
			elif (datetime.now()-start_time).seconds > MODEM_RESPONSE_READ_TIMEOUT:
				return False

	except:
		print ("Error in read_modem_response function...")
		return False
#==========================


# Call the COM Port function
detect_COM_port()