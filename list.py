list = [
	5368,
	5367,
	5369,
	5022,
	5354,
]

for x in range(len(list)):
	#print (list[x])
	#tonumero = list[x]
	#tonumero = str(tonumero)
	tonumero = str(list[x])
	print ("The original number is " + tonumero)
	VTSvalue=(tonumero[0]+","+tonumero[1]+","+tonumero[2]+","+tonumero[3])
	print("AT+ATS=\"" + VTSvalue +"\"")		#AT+VTS="5,3,6,8"

