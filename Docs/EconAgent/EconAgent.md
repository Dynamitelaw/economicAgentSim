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
* ConnectionNetwork interactions
* utility calculations
* marketplace updates and polling
* nutrition tracking (if agent is a person)

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

### Methods
The following are the methods intended for use by the agent controller. There are more methods, but they are used internally, and should not be called by an agent controller.

#### Network
```python
Agent.sendPacket(packet)
```
	Sends a **NetworkPacket** over the connection network.

#### Accounting
##### Labor Income
```python
Agent.enableLaborIncomeTracking()
```
	Enables the tracking of labor income.

```python
Agent.getTotalLaborIncome()
```
	Gets the total labor income from the start of the simulation.

```python
Agent.getAvgLaborIncome()
```
	Gets the current exponential moving average labor income per step. 

#### Currency

#### Item Production/Consumption

#### Item Trading

#### Land Allocation/Trading

#### Labor

#### Marketplace

##### Item MarketplaceItem

##### Land MarketplaceItem

##### Labor MarketplaceItem

#### Utility

#### Time

#### Food

#### Misc