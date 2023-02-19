# EconAgent.py
---
## Agent Class
The Agent class is a generic class used by all agents running in a simulation.

The behavior and actions of any given agent instance is decided by it's controller, which handles all decision making.
The Agent class is instead responsible for the controller's interface to the rest of the simulation.

The Agent class handles:
* item transfers
* item consumption
* item production
* employment contracts
* currency transfers
* trade execution
* land holdings and allocation
* land transfers
* currency balance management
* item inventory management
* [ConnectionNetwork interactions](NetworkPackets.md)
* utility calculations
* marketplace updates and polling
* nutrition tracking (if agent is a person)

---
### Initialization
Because simulations are split into multiple processes, instances of the Agent class cannot be initialized outside of the process they'll be run in. 
This is because they contain [thread locks](https://docs.python.org/3/library/threading.html#lock-objects), which cannot be pickled, and therefore cannot be transfered between two different processes.

To get around this, we instead initialize agents indirectly using the **AgentSeed** class. This class is just a container for the initialization variables needed by the Agent class. Once the AgentSeed is passed to it's home process, the Agent can be initialized by calling the spawnAgent method.
```python
#Create agent seed in manager process
seedObj = AgentSeed(agentId, agentType=None, ticksPerStep=24, settings={}, simManagerId=None, itemDict=None, allAgentDict=None, logFile=True, fileLevel="INFO", outputDir="OUTPUT", disableNetworkLink=False)
#Spawn agent in the simulation process
agentObj = seedObj.spawnAgent()
```
Args:
* **agentId**: \<str\> Name of the agent. This should be unique, since it is used by the ConnectionNetwork to route packets.
* **agentType**: \<str\> Type of agent. This determines which controller the agent will instantiate.
* **ticksPerStep**: \<int\> Amount of ticks that are granted per simulation step.
* **settings**: \<dict\> This dict is passed on to the agent controller, allowing for controller configuration. The agent mostly ignores it.
* **simManagerId**: \<str\> The ID of the simulation manager
* **itemDict**: \<dict\> A dictionary of all possible item types
* **allAgentDict**: \<dict\> A dictionary of all agents in the simulation. This is not currently used for anything.
* **logFile**: \<bool\> Enable log files for this agent
* **fileLevel**: \<str\> If log files are enabled, this string defines the threshold of what is dumped to the log file. Options are: CRITICAL, ERROR, WARNING, INFO, DEBUG
* **outputDir**: \<str\> The output path of this simulation
* **disableNetworkLink**: \<bool\> If True, the agent will ignore incoming packets, and will not send any packets. This is only used for testing, when you want to interact with an agent directly rather than over the network.

---
### Methods
The following are the methods intended for use by the agent controller. There are more methods, but they are used internally, and should not be called by an agent controller.

#### Network
```python
Agent.sendPacket(packet)	#Sends a NetworkPacket over the connection network.
```
[Network Packet Types](NetworkPackets.md)

#### Accounting
```python
Agent.enableLaborIncomeTracking()	#Enables the tracking of labor income.
Agent.getTotalLaborIncome()		#Gets the total labor income from the start of the simulation.
Agent.getAvgLaborIncome()		#Gets the current exponential moving average labor income per step. 
Agent.resetLaborIncome()		#Resets the total labor income to 0. 
```
```python
Agent.enableLaborExpenseTracking()	#Enables the tracking of labor expenses.
Agent.getTotalLaborExpense()		#Gets the total labor expenses from the start of the simulation.
Agent.getAvgLaborExpense()		#Gets the current exponential moving average labor expenses per step. 
Agent.resetLaborExpense()		#Resets the total labor expenses to 0. 
```
```python
Agent.enableTradeRevenueTracking()	#Enables the tracking of item trading revenue.
Agent.getTotalTradeRevenue()		#Gets the total item trading revenue from the start of the simulation.
Agent.getAvgTradeRevenue()		#Gets the current exponential moving average trading revenue per step. 
Agent.resetTradeRevenue()		#Resets the total trading revenue to 0. 
```
```python
Agent.enableItemExpensesTracking()	#Enables the tracking of item trading expenses.
Agent.getTotalItemExpenses()		#Gets the total item trading expenses from the start of the simulation.
Agent.getAvgItemExpenses()			#Gets the current exponential moving average trading expenses per step. 
Agent.resetItemExpenses()			#Resets the total trading expenses to 0. 
```
```python
Agent.enableLandRevenueTracking()	#Enables the tracking of land sale revenue.
Agent.getTotalLandRevenue()		#Gets the total land sale revenue from the start of the simulation. 
Agent.resetLandRevenue()		#Resets the total land sale revenue to 0. 
```
```python
Agent.enableLandExpensesTracking()	#Enables the tracking of land sale expenses.
Agent.getTotalLandExpenses()		#Gets the total land sale expenses from the start of the simulation. 
Agent.resetLandExpenses()		#Resets the total land sale expenses to 0. 
```
```python
Agent.enableCurrencyInflowTracking()	#Enables the tracking of currency inflow.
Agent.getTotalCurrencyInflow()		#Gets the total currency inflow from the start of the simulation.
Agent.getAvgCurrencyInflow()		#Gets the current exponential moving average of curreny inflow per step. 
Agent.getStepCurrencyInflow()		#Resets the currency inflow for the previous simulation step. 
Agent.resetCurrencyInflow()		#Resets the total currency inflow to 0. 
```
```python
Agent.enableCurrencyOutflowTracking()	#Enables the tracking of currency outflow.
Agent.getTotalCurrencyOutflow()		#Gets the total currency outflow from the start of the simulation.
Agent.getAvgCurrencyOutflow()		#Gets the current exponential moving average of curreny outflow per step. 
Agent.getStepCurrencyOutflow()		#Resets the currency outflow for the previous simulation step. 
Agent.resetCurrencyOutflow()		#Resets the total currency outflow to 0. 
```
```python
Agent.getAccountingStats()	#Returns a dictionary of all accounting stats
```

#### Currency
```python
Agent.getCurrencyBalance()	#Returns the current cash balance
```
```python
Agent.sendCurrency(centsm recipientId)	#Sends currency to another agent. Returns True is successful, False if not
```
```python
#WARNING: This prints new currency when called directly. Should only be called directly during simulation setup.
Agent.receiveCurrency(cents)	#Add currency to the agent's balance
```

#### Item Production/Consumption
```python
Agent.sendItem(itemPackage, recipientId)	#Send an item to another agent. Returns True is successful, False if not
Agent.consumeItem(itemPackage)	#Consume an item. Returns True is successful, False if not
```
```python
#WARNING: This spawns new items from the ether when called directly. Should only be called directly during simulation setup.
Agent.receiveItem(itemPackage)	#Add an item to an agent's inventory
```
```python
Agent.produceItem(itemContainer)		#Produce an item. Returns an itemContainer if successful, False if not
Agent.getMaxProduction(itemId)			#Get the maximum amount of an item this agent can produce
Agent.getProductionInputDeltas(itemId, stepProductionQuantity)	#Get a dictionary of input surpluses and deficits for a target production quantity per step
Agent.getProductionInputDeficit(itemId)		#Get a dictionary of input deficits for a target production quantity per step
Agent.getProductionInputSurplus(itemId)		#Get a dictionary of input deficits for a target production quantity per step
```

#### Item Trading
```python
Agent.sendTradeRequest(request, recipientId)	#Send a <TradeRequest> to another agent. Will execute trade if accepted
```

#### Land Allocation/Trading
```python
Agent.deallocateLand(allocationType, hectares)	#Deallocate land from a particular use. Returns True is successful, False if not
Agent.allocateLand(allocationType, hectares)	#Allocate land for a particular use. Returns True is successful, False if not
```
```python
Agent.sendLandTradeRequest(request, recipientId)	#Send a <LandTradeRequest> to another agent. Will execute trade if accepted
Agent.sendLand( allocation, hectares, recipientId)	#Send land to another agent. Returns True is successful, False if not
```
```python
#WARNING: This spawns new land when called directly. Should only be called directly during simulation setup.
Agent.receiveLand(itemId, stepProductionQuantity)	#Get a dictionary of input surpluses and deficits for a target production quantity per step
```

#### Labor
```python
Agent.sendJobApplication(laborListing)	#Apply for a <LaborListing>. Returns True is application accepted, False if not
Agent.cancelLaborContract(laborListing)	#Unilateraly cancel a <LaborContract>
```
```python
Agent.getNetContractedEmployeeLabor()	#Returns a dictionary of all current labor contracts in which this agent is the employer, organized by skill level
Agent.getAllLaborContracts()		#Returns a list of all current labor contracts
```

#### Marketplaces
```python
Agent.updateItemListing(itemListing)			#Update the Item Marketplace with an <ItemListing>
Agent.removeItemListing(itemListing)			#Removes an <ItemListing> from the Item Marketplace
Agent.sampleItemListings(itemContainer, sampleSize=3)	#Returns a random sampling of ItemListings from the Item Marketplace, where ItemListing.itemId == itemContainer.id
Agent.acquireItem(itemContainer, sampleSize=5)		#Automatically attempt to acquire an item for the lowest price. Will return an itemContainer of acquired items.
```
```python
Agent.updateLaborListing(laborListing)			#Update the Labor Marketplace with an <LaborListing>
Agent.removeLaborListing(laborListing)			#Removes an <LaborListing> from the Labor Marketplace
Agent.sampleLaborListings(sampleSize=3, maxSkillLevel=-1, minSkillLevel=0)	#Returns a random sampling of LaborListings from the Labor Marketplace
```
```python
Agent.updateLandListing(laborListing)			#Update the Land Marketplace with an <LandListing>
Agent.removeLandListing(laborListing)			#Removes an <LandListing> from the Land Marketplace
Agent.sampleLandListings(allocation, hectares, sampleSize=3)	#Returns a random sampling of LandListings from the Land Marketplace
```

#### Utility
```python
Agent.getMarginalUtility(itemId)	#Get the marginal utility of an item
```

#### Time
```python
Agent.subcribeTickBlocking()	#Notify the simulation manager that you need to be included in simulation step synchronization. Should be called by the controller during simulation setup.
Agent.relinquishTimeTicks()	#Use up all remaining ticks and wait for the next simulation step
```

#### Food
```python
Agent.enableHunger(autoEat=True)	#Enable nutrition tracking for this agent. If autoEat is set to True, agent will automatically purchase and consume required food at the start of each simulation step.	
```

#### Misc
```python
Agent.saveCheckpoint(filePath=None)	#Saves current agent state into a checkpoint file. Will determine it's own filepath if filePath is not defined
Agent.loadCheckpoint(filePath=None)	#Attempts to load agent state from checkpoint file. Returns true if successful, False if not. Will try to find the checkpoint file if filePath is not specified.
Agent.startController()			#Agent will send a CONTROLLER_START packet to it's controller.
Agent.commitSuicide()			#Agent will send a KILL_AGENT packet to itself and it's controller.
```

---
## Sub Classes
These classes are used by the Agent class for various functions.
* **UtilityFunction** : Determines the utility for an object for a particular agent.
* **ProductionFunction** : Used to calculate production costs for a given item, as well as handling item production.
* **NutritionTracker** : Keeps track of an agent's nutritional levels, as well as food consumption.
* **LandAllocationQueue** : Keeps track of land that is currently being allocated.
* **AgentCheckpoint** : This class stores information on current agent state for saving to and loading from simulation checkpoints.