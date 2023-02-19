# NetworkClasses.py
---
## NetworkPacket Class
Network packets are how agents interface with the rest of the simulation. They are sent over the Connection Network.
### Initialization
```python
packet = NetworkPacket(senderId, msgType, destinationId=None, payload=None, transactionId=None)
```
Args:
* **senderId**: \<str\> Name of the agent sending the packet
* **msgType**: \<PACKET_TYPE\> Type of packet. Must be a PACKET_TYPE enum
* **destinationId**: \<str\> Name of the destination agent. Required if sending a packet to a particular agent.
* **payload**: Payload of the packet. Can be any pickle-safe python object.
* **transactionId**: \<str\> The ID of a larger transaction. If a packet is a single email, the transactionId is the email subject that can be shared among multiple packets. Used by the Agent class to handle interactions that require multiple packets between agents.
---

## PACKET_TYPE Enums

### Network Packets
```python
KILL_PIPE_AGENT
	#If sent to an agent, the agent will send a KILL_PIPE_NETWORK packet to the network, then kill it's monitoring thread

KILL_ALL_BROADCAST
	#Equivalent to sending a KILL_PIPE_AGENT to every agent on the network

KILL_PIPE_NETWORK
	#If sent from an agent, the connection network will delete it's connection to the agent and kill it's monitoring thread

SNOOP_START
	#payload = <dict> {msgType: <bool>, ...}
	#If sent from the statistics gatherer, the network will set up a snoop protocol. Afterwards, all packets with the specified msgTypes (incommingPacket) will be fowarded to the statistics gatherer

ERROR
	#If send to an agent, the agent will print out the packet in an error logger. Currently only used for network errors.
```

### Trade Packets
```python
CURRENCY_TRANSFER
	#payload = <dict> {"paymentId": <str>, "cents": <int>}
	#Transfer currency (amount="cents") from packet sender to packet recipient

CURRENCY_TRANSFER_ACK
	#payload = <dict> {"paymentId": <str>, "transferSuccess": <bool>}
	#Sent from currency recipient to currency sender

ITEM_TRANSFER
	#payload = <dict> {"transferId": <str>, "item": <ItemContainer>}
	#Transfer an item from sender to recipient

ITEM_TRANSFER_ACK
	#payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	#Sent from item recipient to item sender

TRADE_REQ
	#payload = <TradeRequest>

TRADE_REQ_ACK
	#payload = <dict> {"tradeRequest": <TradeRequest>, "accepted": <bool>}

LAND_TRANSFER
	#payload = <dict> {"transferId": <str>, "allocation": <str>, "hectares": <float>}
	#Transfer land from sender to recipient

LAND_TRANSFER_ACK
	#payload = <dict> {"transferId": <str>, "transferSuccess": <bool>}
	#Sent from land recipient to land sender

LAND_TRADE_REQ
	#payload = <LandTradeRequest>

LAND_TRADE_REQ_ACK
	#payload = <dict> {"tradeRequest": <LandTradeRequest>, "accepted": <bool>}
```

### Labor Packets
```python
LABOR_APPLICATION
	#payload = <LaborContract>
	#If sent to an agent, it will foward the contract to its controller for evaluation

LABOR_APPLICATION_ACK
	#payload = <dcit> {"laborContract": <LaborContract>, "accepted": <bool>}
	#Sent to the agent that applied for a job. Payload is True is accepted, False if not.

LABOR_TIME_SEND
	#payload = <dict> {"ticks": <int> ticks, "skillLevel": <float> self.skillLevel}
	#Used by an agent sending their time to their employer

LABOR_CONTRACT_CANCEL
	#payload = <LaborContract>
	#If sent to an agent, it will cancel the specified labor contract

LABOR_CONTRACT_CANCEL_ACK
	#payload = <dict> {"cancellationSuccess": <bool>, "laborContract": <LaborContract>}
	#Sent in response to a LABOR_CONTRACT_CANCEL
```

### Market Packets
```python
ITEM_MARKET_UPDATE
	#payload = <ItemListing>
	#Will update the agent's item listing in the ItemMarketplace

ITEM_MARKET_REMOVE
	#payload = <ItemListing>
	#Will remove the agent's item listing in the ItemMarketplace

ITEM_MARKET_SAMPLE
	#payload = <dict> {"itemContainer": <ItemContainer>, "sampleSize": <int>}
	#Request a sample of sellers for a given item from the ItemMarketplace

ITEM_MARKET_SAMPLE_ACK
	#payload = <list> [<ItemListing>, ...]
	#Returns a list of item listings

LABOR_MARKET_UPDATE
	#payload = <LaborListing>
	#Will update the agent's labor listing in the LaborMarketplace

LABOR_MARKET_REMOVE
	#payload = <LaborListing>
	#Will remove the agent's labor listing in the LaborMarketplace

LABOR_MARKET_SAMPLE
	#payload = <dict> {"maxSkillLevel": <float>, "minSkillLevel": <float>, "sampleSize": <int>}
	#Request a sample of sellers for a given labor from the LaborMarketplace

LABOR_MARKET_SAMPLE_ACK
	#payload = <list> [<LaborListing>, ...]
	#Returns a list of labor listings

LAND_MARKET_UPDATE
	#payload = <LandListing>
	#Will update the agent's land listing in the LandMarketplace

LAND_MARKET_REMOVE
	#payload = <LandListing>
	#Will remove the agent's land listing in the LandMarketplace

LAND_MARKET_SAMPLE
	#payload = <dict> {"allocation": <str>, "hectares": <float>, "sampleSize": <int>}
	#Request a sample of sellers for a given land type from the LandMarketplace

LAND_MARKET_SAMPLE_ACK
	#payload = <list> [<LandListing>, ...]
	#Returns a list of land listings
```

### Other Agent Packets
```python
PRODUCTION_NOTIFICATION
	#payload = <ItemContainer>
	#Sent when an item is produced by an agent. Is only fowarded if snooped on, otherwise ignored

INFO_REQ
	#payload = <InfoRequest>
	#Request information from an agent

INFO_REQ_BROADCAST
	#payload = <InfoRequest>
	#Request information from an agent

INFO_RESP
	#payload = <InfoRequest>
	#Response to information request

CONTROLLER_START
	#Tells the agent to start it's controller by caling controller.controllerStart()

CONTROLLER_START_BROADCAST
	#Tells all agents to start their controllers by caling controller.controllerStart()

ERROR_CONTROLLER_START
	#Sent by an agent if they could not start their controller

CONTROLLER_MSG
	#The recipient agent will foward this packet to it's controller.

CONTROLLER_MSG_BROADCAST
	#All agents will foward this packet to their controller
```

### Simulation management
```python
TICK_BLOCK_SUBSCRIBE:
	#Sent by a controller to the ConnectionNetwork. Tells the network to block simulation step progress until controller send a TICK_BLOCKED message

TICK_BLOCKED
	#Sent by a controller to the ConnectionNetwork. Tells the network that the controller is out of time ticks and cannot execute more actions

TICK_BLOCKED_ACK
	#Sent by the ConnectionNetwork to the blocked agent, so that the agent knows it's TICK_BLOCKED was registered

TICK_GRANT
	#payload = <int> ticks
	#Send by the simulation manager to an agent at the beginning of a step.

TICK_GRANT_BROADCAST
	#payload = <int> ticks
	#Send by the simulation manager to all agents at the beginning of a step.

TERMINATE_SIMULATION
	#If sent to the simulation manager, it will terminate the simulation

PROC_STOP
	#If sent to a simulation process, it will kill itself

SAVE_CHECKPOINT
	#If send to an agent, it will save a checkpoint file

SAVE_CHECKPOINT_BROADCAST
	#If sent, all agents and marketplaces will save a checkpoint
	
LOAD_CHECKPOINT
	#payload = <str> checkpoint path
	#If sent to an agent, it will load a checkpoint

LOAD_CHECKPOINT_BROADCAST
	#payload = <str> checkpoint path
	#If sent, all agents and markets will load a checkpoint
```

### Controller messages
These message types are fowarded to the agent controller, so they have no hardcoded behavior.
The following are the current types and their intended usage.
```python
#controllerMessage is expected to be a <NetworkPacket> obj
msg = NetworkPacket(msgType=PACKET_TYPE.CONTROLLER_MSG, payload=controllerMessage)
msgBroadcast = NetworkPacket(msgType=PACKET_TYPE.CONTROLLER_MSG_BROADCAST, payload=controllerMessage)
```
```python
ADVANCE_STEP
	#Sent by the ConnectionNetwork to the SimulationManager. Tells the manager that all agents are ready for the next simulation step
STOP_TRADING:
	#Tells the recipient controller that the simulation is ending, and to cease all trading activity
TICK_GRANT:
	#payload=<int> tickAmount
	#Grants the recipient controller time ticks. Sent by the SimulationManager to synchronize sim time.
PROC_READY
	#Sent by child process to the SimulationManager. Tells the manager that all agents in the process have been instantiated
PROC_ERROR
	#Sent by child process to the SimulationManager. Tells the manager that there was an error during agent instantiation
```