# Simulation Settings File
runSim.py takes in a json file as an argument. This file defines all simulation parameters.

## Setting Fields
* **name** : \<str\> Name of the simulation. This determines the output folder.
* **description** : \<str\> *(optional)* Description of the simulation.
* **settings** : \<json\> Json object that contains simulation parmaters.
	* **AgentNumProcesses** : \<int\> Number of parallel processes that agent simulation will be split across. For best performance, this should be NUM_CPU_CORES - 1
	* **SimulationSteps** : \<int\> Number of steps the simulation will run for
	* **TicksPerStep** : \<int\> How many ticks (~hours) are granted in each step. Usually 16, since we presume everyone needs 8 hours of sleep (unless you're a grad student).
	* **CheckpointFrequency** : \<int\> *(optional)* How often (in steps) will the simulation create a save checkpoint. Especially useful for long simulations.
	* **InitialCheckpoint** : \<str\> *(optional)* Directory path of a saved checkpoint. Will load the checkpoint as initial simulation state.
	* **AgentSpawns** : \<json\> Json object that contains all the agents you want to spawn for the simulation. Below is the format for each spawn object:
		* *\<str\>SpawnName* : \<json\> The spawn name is an arbitrary agent name prefix. Must be unique. The data for this field is a json object describing *SpawnName*
			* *\<str\>AGENT_TYPE* : \<json\> *AGENT_TYPE* denotes the type of controller you want these agents to use. The data for this field is a json object describing spawn settings.
				* **quantity** : \<int\> How many of *SpawnName.AGENT_TYPE* do you want to spawn
				* **settings** : \<json\> *(optional)* Spawn settings for *SpawnName.AGENT_TYPE*. These are passed directly to the controller, so the format is dependent on *AGENT_TYPE*
	* **Statistics** : \<json\> *(optional)* Json object that contains all the statistics you want to dump for the simulation. Below is the format for each stat object:
		* *\<str\>StatName* : \<json\> This is an arbitrary name for this statistic. Must be unique. The data for this field is a json object describing *StatName*
			* *\<str\>STAT_TRACKER_TYPE* : \<json\> *STAT_TRACKER_TYPE* denotes the type of stat tracker you want to use. The data for this field is a json object describing tracker settings. The format of these tracker settings are dependent on *STAT_TRACKER_TYPE*.

Example file:
```json
{
	"name": "MySimulation",
	"description": "Test simulation with dummy parameters.",
	"settings": {
		"AgentNumProcesses": 4,
		"SimulationSteps": 50,
		"TicksPerStep": 16,
		"CheckpointFrequency": 10,
		"InitialCheckpoint": "MyCheckpointPath",
		"AgentSpawns":{
			"AppleFarm": {
				"TestFarmCompetetiveV3":{
					"quantity": 3,
					"settings": {
						"itemId": "apple",
						"startingProductionRate": 20,
						"StartSkew": 9
					}
				}
			},
			"ButterFarm": {
				"TestFarmCompetetiveV3":{
					"quantity": 3,
					"settings": {
						"itemId": "butter",
						"startingProductionRate":6.68,
						"StartSkew": 9
					}
				}
			},
			"River": {
				"TestSpawner":{
					"quantity": 1,
					"settings": {
						"itemId": "water",
						"spawnRate": 1440
					}
				}
			},
			"FarmWorker": {
				"TestFarmWorkerV2":{
					"quantity": 100
				}
			}
		},
		"Statistics": {
			"LaborStats": {
				"LaborContractTracker": {
					"OuputPath": "LaborStats/AllLabor.csv"
				}
			},
			"AppleMarket":{
				"ItemPriceTracker":{
					"id": "apple",
					"OuputPath": "FoodMarket/apple/ApplePrice.csv"
				},
				"ProductionTracker":{
					"id": "apple",
					"OuputPath": "FoodMarket/apple/AppleProduction.csv"
				}
			}
		}
	}
}
```

## Statistics Trackers
These are all the current statistic tracker types, and their settings formats.
* **LaborContractTracker** : Tracks all currently active LaborContracts by snooping on LABOR_APPLICATION_ACK and LABOR_CONTRACT_CANCEL packets.
```json
"LaborContractTracker": {
	"OuputPath": "My/Output/Path.csv"
}
```
* **ConsumptionTracker** : Tracks net consumption by snooping on TRADE_REQ_ACK packets.
```json
"ConsumptionTracker": {
	"ConsumerClasses": ["TestFarmWorker_Rule", "TestFarmWorker_AI"],
	"OuputPath": "My/Output/Path.csv"
}
```
* **ItemPriceTracker** : Tracks the distribution of sale prices for a particular item by snooping on TRADE_REQ_ACK packets.
```json
"ItemPriceTracker": {
	"id": "apple",
	"OuputPath": "My/Output/Path.csv"
}
```
* **ProductionTracker** : Tracks the net production of a particular item by snooping on PRODUCTION_NOTIFICATION packets.
```json
"ProductionTracker": {
	"id": "apple",
	"OuputPath": "My/Output/Path.csv"
}
```
* **AccountingTracker** : Tracks the accounting stats of particular agents by sending out INFO_REQ packets.
```json
"AccountingTracker": {
	"AgentFilters": ["PeaFarm0"],
	"OuputPath": "My/Output/Path.csv"
}
```
					"OuputPath": "LaborStats/AllLabor.csv"
				}
				"ConsumptionTracker": {
					"ConsumerClasses": ["TestFarmWorker"],
					"OuputPath": "ConsumptionStats/PrivateConsumption.csv"
				}
				"ItemPriceTracker":{
					"id": "apple",
					"OuputPath": "FoodMarket/apple/ApplePrice.csv"
				},
				"ProductionTracker":{
					"id": "apple",
					"OuputPath": "FoodMarket/apple/AppleProduction.csv"
				},
				"AccountingTracker":{
					"AgentFilters": ["PeaFarm0"],
					"OuputPath": "FoodMarket/chickpea/accounting/ChickpeaFarm0_Accounting.csv"
				}