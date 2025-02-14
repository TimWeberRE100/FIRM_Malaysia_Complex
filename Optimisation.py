# To optimise the configurations of energy generation, storage and transmission assets
# Copyright (c) 2019, 2020 Bin Lu, The Australian National University
# Licensed under the MIT Licence
# Correspondence: bin.lu@anu.edu.au

from scipy.optimize import differential_evolution
from argparse import ArgumentParser
import datetime as dt
import csv

parser = ArgumentParser()
parser.add_argument('-i', default=2000, type=int, required=False, help='maxiter=4000, 400')
parser.add_argument('-p', default=5, type=int, required=False, help='popsize=2, 10')
parser.add_argument('-m', default=0.5, type=float, required=False, help='mutation=0.5')
parser.add_argument('-r', default=0.3, type=float, required=False, help='recombination=0.3')
parser.add_argument('-e', default=5, type=int, required=False, help='per-capita electricity = 5, 10, 20 MWh/year')
parser.add_argument('-n', default='APG_MY_Isolated', type=str, required=False, help='APG_Full, APG_PMY_Only, APG_BMY_Only, APG_MY_Isolated, SB, SW...')
parser.add_argument('-s', default='HVAC', type=str, required=False, help='HVDC, HVAC')
parser.add_argument('-H', default='True', type=str, required=False, help='Hydrogen Firming=True,False')
parser.add_argument('-b', default='True', type=str, required=False, help='Battery Coopimisation=True,False')
args = parser.parse_args()

scenario = args.s
node = args.n
percapita = args.e

if args.H == "True":
    gasScenario = True
elif args.H == "False":
    gasScenario = False
else:
    print("-H must be True or False")
    exit()

if args.b == "True":
    batteryScenario = True
elif args.b == "False":
    batteryScenario = False
else:
    print("-b must be True or False")
    exit()

from Input import *
from Simulation import Reliability
from Network import Transmission

def F(x):
    '''This is the objective function.'''

    # Initialise the optimisation
    S = Solution(x)

    CGas = np.nan_to_num(np.array(S.CGas))
    
    # Simulation with only baseload
    Deficit_energy1, Deficit_power1, Deficit1, DischargePH1, DischargeB1 = Reliability(S, hydro=baseload, bio=np.zeros(intervals), gas=np.zeros(intervals)) # Sj-EDE(t, j), MW
    Max_deficit1 = np.reshape(Deficit1, (-1, 8760)).sum(axis=-1) # MWh per year
    PFlexible_Gas = Deficit1.max() * pow(10, -3) # GW

    # Simulation with only baseload and hydro (cheapest)
    Deficit_energy2, Deficit_power2, Deficit2, DischargePH2, DischargeB2 = Reliability(S, hydro=np.ones(intervals) * CHydro.sum() * pow(10,3), bio=np.zeros(intervals), gas=np.zeros(intervals))
    Max_deficit2 = np.reshape(Deficit2, (-1, 8760)).sum(axis=-1) # MWh per year
    PBio_Gas = Deficit2.max() * pow(10, -3) # GW

    # Simulation with only baseload, hydro and bio (next cheapest)
    Deficit_energy3, Deficit_power3, Deficit3, DischargePH3, DischargeB3 = Reliability(S, hydro=np.ones(intervals) * CHydro.sum() * pow(10,3), bio = np.ones(intervals) * CBio.sum() * pow(10, 3), gas=np.zeros(intervals))
    Max_deficit3 = np.reshape(Deficit3, (-1, 8760)).sum(axis=-1) # MWh per year
    PGas = Deficit3.max() * pow(10, -3) # GW
    
    # Assume all storage provided by PHES (lowest efficiency i.e. worst cast). Look at maximum generation years for energy penalty function
    GHydro = resolution * (Max_deficit1 - Max_deficit2).max() / efficiencyPH + 8760*CBaseload.sum() * pow(10,3)
    GBio = resolution * (Max_deficit2 - Max_deficit3).max() / efficiencyPH
    GGas = resolution * (Max_deficit3).max() / efficiencyPH
    
    # Power and energy penalty functions
    PenEnergy = (max(0, GHydro - Hydromax) + max(0, GBio - Biomax) + max(0, GGas - Gasmax))*pow(10,3)
    PenPower = (max(0,PFlexible_Gas - (CPeak.sum() + CGas.sum())) + max(0, PBio_Gas - (CBio.sum() + CGas.sum())) + max(0, PGas - CGas.sum()))*pow(10,3)

    # Simulation with baseload, all existing capacity, and all hydrogen
    Deficit_energy, Deficit_power, Deficit, DischargePH, DischargeB = Reliability(S, hydro=np.ones(intervals) * CHydro.sum() * pow(10,3), bio = np.ones(intervals) * CBio.sum() * pow(10, 3), gas=np.ones(intervals) * CGas.sum() * pow(10, 3))
    
    # Deficit penalty function
    PenDeficit = max(0, Deficit.sum() * resolution - S.allowance)*pow(10,3)

    # Existing capacity generation profiles    
    gas = np.clip(Deficit3, 0, CGas.sum() * pow(10, 3))
    bio = np.clip(Deficit2 - Deficit3, 0, CBio.sum() * pow(10, 3))
    hydro = np.clip(Deficit1 - Deficit2, 0, CHydro.sum() * pow(10, 3)) + baseload

    # Simulation using the existing capacity generation profiles - required for storage average annual discharge
    Deficit_energy, Deficit_power, Deficit, DischargePH, DischargeB = Reliability(S, hydro=hydro, bio=bio, gas=gas)

    # Discharged energy from storage systems
    GPHES = DischargePH.sum() * resolution / years * pow(10,-6) # TWh per year
    GBattery = DischargeB.sum() * resolution / years * pow(10,-6)

    # Transmission capacity calculations
    TDC = Transmission(S) if 'APG' in node else np.zeros((intervals, len(TLoss))) # TDC: TDC(t, k), MW
    CDC = np.amax(abs(TDC), axis=0) * pow(10, -3) # CDC(k), MW to GW

    # Transmission penalty function
    PenDC = max(0, CDC[9] - CDC9max) * pow(10, 3) # GW to MW
    PenDC += max(0, CDC[10] - CDC10max) * pow(10, 3) # GW to MW
    PenDC += max(0, CDC[11] - CDC11max) * pow(10, 3) # GW to MW
    PenDC *= pow(10, 3) # Blow up penalty function

    # Maximum annual electricity generated by existing capacity
    GGas = resolution * gas.sum() / years / efficiencyPH
    GHydro = resolution * hydro.sum() / years / efficiencyPH
    GBio = resolution * bio.sum() / years / efficiencyPH
    
    # Average annual electricity imported through external interconnections
    GInter = sum(sum(S.GInter)) * resolution / years if len(S.GInter) > 0 else 0

    # Levelised cost of electricity calculation
    cost = factor * np.array([sum(S.CPV), GInter * pow(10,-6), sum(S.CPHP), S.CPHS, sum(S.CBP), S.CBS] + list(CDC) + [sum(S.CPV), GHydro * pow(10, -6), GBio * pow(10,-6), CGas.sum(), GGas * pow(10, -6), GPHES, GBattery, 0, 0]) # $b p.a.
    cost = cost.sum()
    loss = np.sum(abs(TDC), axis=0) * TLoss
    loss = loss.sum() * pow(10, -9) * resolution / years # PWh p.a.
    LCOE = cost / abs(energy - loss)
    
    with open('Results/record_{}_{}_{}_{}_{}.csv'.format(node,scenario,percapita,batteryScenario,gasScenario), 'a', newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(np.append(x,[PenDeficit+PenEnergy+PenPower+PenDC,PenDeficit,PenEnergy,PenPower,PenDC,LCOE]))

    Func = LCOE + PenDeficit + PenEnergy + PenPower + PenDC
    
    return Func 

if __name__=='__main__':
    starttime = dt.datetime.now()
    print("Optimisation starts at", starttime)

#    lb = [0.]       * pzones + [0.]     * wzones + contingency_ph   + contingency_b     + [0.]      + [0.]     + [0.]    * inters + [0.] * nodes
#    ub = [10000.]   * pzones + [300]    * wzones + [10000.] * nodes + [10000.] * nodes  + [100000.] + [100000] + [1000.] * inters + [50.] * nodes

    lb = [0.]       * pzones + contingency_ph   + contingency_b                 + [0.]      + [0.]      + [0.]    * inters + ([0.] * (nodes - inters) + inters * [0])
    ub = pv_ub + phes_ub + battery_ub + phes_s_ub + battery_s_ub + inter_ub + gas_ub

    # start = np.genfromtxt('Results/init.csv', delimiter=',')    

    result = differential_evolution(func=F, bounds=list(zip(lb, ub)), tol=0, # init=start,
                                    maxiter=args.i, popsize=args.p, mutation=args.m, recombination=args.r,
                                    disp=True, polish=False, updating='deferred', workers=-1) ###### CHANGE WORKERS BACK TO -1

    with open('Results/Optimisation_resultx_{}_{}_{}_{}_{}.csv'.format(node,scenario,percapita,batteryScenario,gasScenario), 'w', newline="") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(result.x)

    endtime = dt.datetime.now()
    print("Optimisation took", endtime - starttime)

    from Fill import Analysis
    Analysis(result.x,'_{}_{}_{}_{}_{}.csv'.format(node,scenario,percapita,batteryScenario,gasScenario))
