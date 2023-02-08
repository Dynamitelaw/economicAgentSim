import hashlib
import time
from enum import Enum, unique


#Enum for NetworkPacket types
@unique
class PACKET_TYPE(Enum):
	#########################
	# Network Packets
	#########################
	KILL_PIPE_AGENT = 101
	KILL_ALL_BROADCAST = 102
	KILL_PIPE_NETWORK = 103
	SNOOP_START = 104
	ERROR = 105

	#########################
	# Trade Packets
	#########################
	CURRENCY_TRANSFER = 201
	CURRENCY_TRANSFER_ACK = 202

	ITEM_TRANSFER = 211
	ITEM_TRANSFER_ACK = 212

	TRADE_REQ = 221
	TRADE_REQ_ACK = 222

	LAND_TRANSFER = 231
	LAND_TRANSFER_ACK = 232
	LAND_TRADE_REQ = 233
	LAND_TRADE_REQ_ACK = 234

	LABOR_APPLICATION = 241
	LABOR_APPLICATION_ACK = 242
	LABOR_TIME_SEND = 243
	LABOR_CONTRACT_CANCEL = 244
	LABOR_CONTRACT_CANCEL_ACK = 245

	#########################
	# Market Packets
	#########################
	ITEM_MARKET_UPDATE = 301
	ITEM_MARKET_REMOVE = 302
	ITEM_MARKET_SAMPLE = 303
	ITEM_MARKET_SAMPLE_ACK = 304

	LABOR_MARKET_UPDATE = 311
	LABOR_MARKET_REMOVE = 312
	LABOR_MARKET_SAMPLE = 313
	LABOR_MARKET_SAMPLE_ACK = 314

	LAND_MARKET_UPDATE = 321
	LAND_MARKET_REMOVE = 322
	LAND_MARKET_SAMPLE = 323
	LAND_MARKET_SAMPLE_ACK = 324

	#########################
	# Other Agent Packets
	#########################
	PRODUCTION_NOTIFICATION = 401

	INFO_REQ = 411
	INFO_REQ_BROADCAST = 412
	INFO_RESP = 413

	CONTROLLER_START = 421
	CONTROLLER_START_BROADCAST = 422
	ERROR_CONTROLLER_START = 423
	CONTROLLER_MSG = 424
	CONTROLLER_MSG_BROADCAST = 425

	#########################
	# Simulation management
	#########################
	TICK_BLOCK_SUBSCRIBE = 501
	TICK_BLOCKED = 502
	TICK_GRANT = 503
	TICK_GRANT_BROADCAST = 504

	TERMINATE_SIMULATION = 511
	PROC_STOP = 512

	#########################
	# Controller messages
	#########################
	ADVANCE_STEP = 9001
	STOP_TRADING = 9002
	PROC_READY = 9003
	PROC_ERROR = 9004


class NetworkPacket:
	def __init__(self, senderId, msgType, destinationId=None, payload=None, transactionId=None):
		self.msgType = msgType
		self.payload = payload
		self.senderId = senderId
		self.destinationId = destinationId
		self.transactionId = transactionId

		hashStr = "{}{}{}{}{}{}".format(msgType, payload, senderId, destinationId, transactionId, time.time())
		self.hash = hashlib.sha256(hashStr.encode('utf-8')).hexdigest()[:8 ]

	def __str__(self):
		return "({}_{}, {}, {}, {})".format(self.msgType, self.hash, self.senderId, self.destinationId, self.transactionId)

class Link:
	def __init__(self, sendPipe, recvPipe):
		self.sendPipe = sendPipe
		self.recvPipe = recvPipe


'''
#Format
NetworkPacket.msgType
	Info

#########################
# Network Packets
#########################

KILL_PIPE_AGENT
	If sent to an agent, the agent will send a KILL_PIPE_NETWORK packet to the network, then kill it's monitoring thread

KILL_ALL_BROADCAST
	Equivalent to sending a KILL_PIPE_AGENT to every agent on the network

KILL_PIPE_NETWORK
	If sent from an agent, the connection network will delete it's connection to the agent and kill it's monitoring thread

SNOOP_START
	payload = <dict> {msgType: <bool>, ...}
	If sent from the statistics gatherer, the network will set up a snoop protocol. Afterwards, all packets with the specified msgTypes (incommingPacket) will be fowarded to the statistics gatherer

ERROR
	If send to an agent, the agent will print out the packet in an error logger. Currently only used for network errors.

#########################
# Trade Packets
#########################

CURRENCY_TRANSFER
	payload = <dict> {"paymentId": <str>, "cents": <int>}
	Transfer currency (amount="cents") from packet sender to packet recipient

CURRENCY_TRANSFER_ACK
	payload = <dict> {"paymentId": <str>, "transferSuccess": <bool>}
	Sent from currency recipient to currency sender

ITEM_TRANSFER
	payload = <dict> {"transferId": <str>, "item": <ItemContainer>}
	Transfer an item from sender to recipient

ITEM_TRANSFER_ACK
	payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	Sent from item recipient to item sender

TRADE_REQ
	payload = <TradeRequest>

TRADE_REQ_ACK
	payload = <dict> {"tradeRequest": <TradeRequest>, "accepted": <bool>}

LAND_TRANSFER
	payload = <dict> {"transferId": <str>, "allocation": <str>, "hectares": <float>}
	Transfer land from sender to recipient

LAND_TRANSFER_ACK
	payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	Sent from land recipient to land sender

LAND_TRADE_REQ
	payload = <LandTradeRequest>

LAND_TRADE_REQ_ACK
	payload = <dict> {"tradeRequest": <LandTradeRequest>, "accepted": <bool>}

#########################
# Market Packets
#########################

ITEM_MARKET_UPDATE
	payload = <ItemListing>
	Will update the agent's item listing in the ItemMarketplace

ITEM_MARKET_REMOVE
	payload = <ItemListing>
	Will remove the agent's item listing in the ItemMarketplace

ITEM_MARKET_SAMPLE
	payload = <dict> {"itemContainer": <ItemContainer>, "sampleSize": <int>}
	Request a sample of sellers for a given item from the ItemMarketplace

ITEM_MARKET_SAMPLE_ACK
	payload = <list> [<ItemListing>, ...]
	Returns a list of item listings

LABOR_MARKET_UPDATE
	payload = <LaborListing>
	Will update the agent's labor listing in the LaborMarketplace

LABOR_MARKET_REMOVE
	payload = <LaborListing>
	Will remove the agent's labor listing in the LaborMarketplace

LABOR_MARKET_SAMPLE
	payload = <dict> {"maxSkillLevel": <float>, "minSkillLevel": <float>, "sampleSize": <int>}
	Request a sample of sellers for a given labor from the LaborMarketplace

LABOR_MARKET_SAMPLE_ACK
	payload = <list> [<LaborListing>, ...]
	Returns a list of labor listings

LAND_MARKET_UPDATE
	payload = <LandListing>
	Will update the agent's land listing in the LandMarketplace

LAND_MARKET_REMOVE
	payload = <LandListing>
	Will remove the agent's land listing in the LandMarketplace

LAND_MARKET_SAMPLE
	payload = <dict> {"allocation": <str>, "hectares": <float>, "sampleSize": <int>}
	Request a sample of sellers for a given land type from the LandMarketplace

LAND_MARKET_SAMPLE_ACK
	payload = <list> [<LandListing>, ...]
	Returns a list of land listings

#########################
# Other Agent Packets
#########################

PRODUCTION_NOTIFICATION
	payload = <ItemContainer>
	Send when an item is produced by an agent. Is only fowarded if snooped on, otherwise ignored

INFO_REQ
	payload = <InfoRequest>
	Request information from an agent

INFO_REQ_BROADCAST
	payload = <InfoRequest>
	Request information from an agent

INFO_RESP
	payload = <InfoRequest>
	Response to information request

CONTROLLER_START
	Tells the agent to start it's controller by caling controller.controllerStart()

CONTROLLER_START_BROADCAST
	Tells all agents to start their controllers by caling controller.controllerStart()

ERROR_CONTROLLER_START
	Sent by an agent if they could not start their controller

CONTROLLER_MSG
	The recipient agent will foward this packet to it's controller.

CONTROLLER_MSG_BROADCAST
	All agents will foward this packet to their controller


#########################
# Simulation management
#########################
TICK_BLOCK_SUBSCRIBE:
	Sent by a controller to the ConnectionNetwork. Tells the network to block simulation step progress until controller send a TICK_BLOCKED message

TICK_BLOCKED
	Sent by a controller to the ConnectionNetwork. Tells the network that the controller is out of time ticks and cannot execute more actions

#########################
# Controller messages
#########################
These message types are fowarded to the agent controller, so they have no hardcoded behavior.
The following are the current types and their intended usage.

NetworkPacket(msgType="CONTROLLER_MSG|CONTROLLER_MSG_BROADCAST", payload=controllerMessage)

"controllerMessage" is expected to be a <NetworkPacket> obj.

controllerMessage.msgTypes:
	ADVANCE_STEP
		Sent by the ConnectionNetwork to the SimulationManager. Tells the manager that all agents are ready for the next simulation step
	STOP_TRADING:
		Tells the recipient controller to cease all trading activity
	TICK_GRANT:
		payload=<int> tickAmount
		Grants the recipient controller time ticks. Sent by the SimulationManager to synchronize sim time.
	PROC_READY
		Sent by child process to the SimulationManager. Tells the manager that all agents in the process have been instantiated
	PROC_ERROR
		Sent by child process to the SimulationManager. Tells the manager that there was an error during agent instantiation

'''