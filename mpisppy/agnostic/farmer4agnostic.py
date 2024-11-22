# The farmer example for general agnostic with Pyomo as guest language
# This example includes bundles as an option
# ALL INDEXES ARE ZERO-BASED
#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2018 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and 
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain 
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________
#

import pyomo.environ as pyo
import numpy as np
import mpisppy.utils.sputils as sputils

# Use this random stream:
farmerstream = np.random.RandomState()

# to support a hack needed for bundles (ignore if you are not using bundles)
numbuns = 0
bunsize = 0
original_num_scens = None

def scenario_creator(
    scenario_name, use_integer=False, sense=pyo.minimize, crops_multiplier=1,
        num_scens=None, seedoffset=0
):
    """ Create a scenario for the (scalable) farmer example.
    
    Args:
        scenario_name (str):
            Name of the scenario to construct, which might be a bundle.
        use_integer (bool, optional):
            If True, restricts variables to be integer. Default is False.
        sense (int, optional):
            Model sense (minimization or maximization). Must be either
            pyo.minimize or pyo.maximize. Default is pyo.minimize.
        crops_multiplier (int, optional):
            Factor to control scaling. There will be three times this many
            crops. Default is 1.
        num_scens (int, optional):
            Number of scenarios. We use it to compute _mpisppy_probability. 
            Default is None.
        seedoffset (int): used by confidence interval code
    """
    if "scen" == scenario_name[:4] or "Scen" == scenario_name[:4]:
        # scenario_name has the form <str><int> e.g. scen12, foobar7
        # The digits are scraped off the right of scenario_name using regex then
        # converted mod 3 into one of the below avg./avg./above avg. scenarios
        scennum   = sputils.extract_num(scenario_name)
        basenames = ['BelowAverageScenario', 'AverageScenario', 'AboveAverageScenario']
        basenum   = scennum  % 3
        groupnum  = scennum // 3
        scenname  = basenames[basenum]+str(groupnum)

        # The RNG is seeded with the scenario number so that it is
        # reproducible when used with multiple threads.
        # NOTE: if you want to do replicates, you will need to pass a seedoffset
        # as a kwarg to scenario_creator 
        farmerstream.seed(scennum+seedoffset)

        # Check for minimization vs. maximization
        if sense not in [pyo.minimize, pyo.maximize]:
            raise ValueError("Model sense Not recognized")

        # Create the concrete model object
        model = pysp_instance_creation_callback(
            scenname,
            use_integer=use_integer,
            sense=sense,
            crops_multiplier=crops_multiplier,
        )

        # create a varlist, which is used to create a vardata list
        # (This list needs to whatever the guest needs, not what Pyomo needs)
        varlist = [model.DevotedAcreage]
        model._nonant_vardata_list = sputils.build_vardatalist(model, varlist)
        sputils.attach_root_node(model, 0, varlist)

        #Add the probability of the scenario
        if num_scens is not None :
            model._mpisppy_probability = 1/num_scens
        else:
            model._mpisppy_probability = "uniform"
        return model
    
    elif "bund" == scenario_name[:4] or "Bund" == scenario_name[:4]:
        firstnum = int(scenario_name.split("_")[1])
        lastnum = int(scenario_name.split("_")[2])
        assert (lastnum-firstnum+1) == bunsize
        assert num_scens % bunsize != 0, "Due to laziness, we need equal sized bundels"
        snames = [f"scen{i}" for i in range(firstnum, lastnum+1)]

        bunkwargs = {"use_integer": use_integer,
                     "sense": sense,
                     "crops_multiplier": crops_multiplier, 
                     "num_scens":None}
        bunkwargs["seedoffset"] = seedoffset + firstnum

        # it is easy to make the EF in Pyomo; see create_EF
        # Note that it call scenario_creator, but this time it will be
        #    with scenario names.
        bundle = sputils.create_EF(snames, scenario_creator,
                                   scenario_creator_kwargs=bunkwargs,
                                   EF_name=scenario_name,
                                   nonant_for_fixed_vars = False)
        # It simplifies things if we assume that it is a 2-stage problem,
        # or that the bundles consume entire second stage nodes,
        # then all we need is a root node and the only nonants that need to be reported are
        # at the root node (otherwise, more coding is required here to figure out which nodes and Vars
        # are shared with other bundles)
        # Note: farmer is 2 stage.
        nonantlist = [v for idx,v in bundle.ref_vars.items() if idx[0] =="ROOT"]
        sputils.attach_root_node(bundle, 0, nonantlist)
        # scenarios are equally likely so bundles are too
        bundle._mpisppy_probability = 1/numbuns
        return bundle
    else:
        raise RuntimeError (f"Scenario name does not have scen or bund: {scenario_name}")

def pysp_instance_creation_callback(
    scenario_name, use_integer=False, sense=pyo.minimize, crops_multiplier=1
):
    # long function to create the entire model
    # scenario_name is a string (e.g. AboveAverageScenario0)
    #
    # Returns a concrete model for the specified scenario

    # scenarios come in groups of three
    scengroupnum = sputils.extract_num(scenario_name)
    scenario_base_name = scenario_name.rstrip("0123456789")
    
    model = pyo.ConcreteModel(scenario_name)

    def crops_init(m):
        retval = []
        for i in range(crops_multiplier):
            retval.append("WHEAT"+str(i))
            retval.append("CORN"+str(i))
            retval.append("SUGAR_BEETS"+str(i))
        return retval

    model.CROPS = pyo.Set(initialize=crops_init)

    #
    # Parameters
    #

    model.TOTAL_ACREAGE = 500.0 * crops_multiplier

    def _scale_up_data(indict):
        outdict = {}
        for i in range(crops_multiplier):
           for crop in ['WHEAT', 'CORN', 'SUGAR_BEETS']:
               outdict[crop+str(i)] = indict[crop]
        return outdict
        
    model.PriceQuota = _scale_up_data(
        {'WHEAT':100000.0,'CORN':100000.0,'SUGAR_BEETS':6000.0})

    model.SubQuotaSellingPrice = _scale_up_data(
        {'WHEAT':170.0,'CORN':150.0,'SUGAR_BEETS':36.0})

    model.SuperQuotaSellingPrice = _scale_up_data(
        {'WHEAT':0.0,'CORN':0.0,'SUGAR_BEETS':10.0})

    model.CattleFeedRequirement = _scale_up_data(
        {'WHEAT':200.0,'CORN':240.0,'SUGAR_BEETS':0.0})

    model.PurchasePrice = _scale_up_data(
        {'WHEAT':238.0,'CORN':210.0,'SUGAR_BEETS':100000.0})

    model.PlantingCostPerAcre = _scale_up_data(
        {'WHEAT':150.0,'CORN':230.0,'SUGAR_BEETS':260.0})

    #
    # Stochastic Data
    #
    Yield = {}
    Yield['BelowAverageScenario'] = \
        {'WHEAT':2.0,'CORN':2.4,'SUGAR_BEETS':16.0}
    Yield['AverageScenario'] = \
        {'WHEAT':2.5,'CORN':3.0,'SUGAR_BEETS':20.0}
    Yield['AboveAverageScenario'] = \
        {'WHEAT':3.0,'CORN':3.6,'SUGAR_BEETS':24.0}

    def Yield_init(m, cropname):
        # yield as in "crop yield"
        crop_base_name = cropname.rstrip("0123456789")
        if scengroupnum != 0:
            return Yield[scenario_base_name][crop_base_name]+farmerstream.rand()
        else:
            return Yield[scenario_base_name][crop_base_name]

    model.Yield = pyo.Param(model.CROPS,
                            within=pyo.NonNegativeReals,
                            initialize=Yield_init,
                            mutable=True)

    #
    # Variables
    #

    if (use_integer):
        model.DevotedAcreage = pyo.Var(model.CROPS,
                                       within=pyo.NonNegativeIntegers,
                                       bounds=(0.0, model.TOTAL_ACREAGE))
    else:
        model.DevotedAcreage = pyo.Var(model.CROPS, 
                                       bounds=(0.0, model.TOTAL_ACREAGE))

    model.QuantitySubQuotaSold = pyo.Var(model.CROPS, bounds=(0.0, None))
    model.QuantitySuperQuotaSold = pyo.Var(model.CROPS, bounds=(0.0, None))
    model.QuantityPurchased = pyo.Var(model.CROPS, bounds=(0.0, None))

    #
    # Constraints
    #

    def ConstrainTotalAcreage_rule(model):
        return pyo.sum_product(model.DevotedAcreage) <= model.TOTAL_ACREAGE

    model.ConstrainTotalAcreage = pyo.Constraint(rule=ConstrainTotalAcreage_rule)

    def EnforceCattleFeedRequirement_rule(model, i):
        return model.CattleFeedRequirement[i] <= (model.Yield[i] * model.DevotedAcreage[i]) + model.QuantityPurchased[i] - model.QuantitySubQuotaSold[i] - model.QuantitySuperQuotaSold[i]

    model.EnforceCattleFeedRequirement = pyo.Constraint(model.CROPS, rule=EnforceCattleFeedRequirement_rule)

    def LimitAmountSold_rule(model, i):
        return model.QuantitySubQuotaSold[i] + model.QuantitySuperQuotaSold[i] - (model.Yield[i] * model.DevotedAcreage[i]) <= 0.0

    model.LimitAmountSold = pyo.Constraint(model.CROPS, rule=LimitAmountSold_rule)

    def EnforceQuotas_rule(model, i):
        return (0.0, model.QuantitySubQuotaSold[i], model.PriceQuota[i])

    model.EnforceQuotas = pyo.Constraint(model.CROPS, rule=EnforceQuotas_rule)

    # Stage-specific cost computations;

    def ComputeFirstStageCost_rule(model):
        return pyo.sum_product(model.PlantingCostPerAcre, model.DevotedAcreage)
    model.FirstStageCost = pyo.Expression(rule=ComputeFirstStageCost_rule)

    def ComputeSecondStageCost_rule(model):
        expr = pyo.sum_product(model.PurchasePrice, model.QuantityPurchased)
        expr -= pyo.sum_product(model.SubQuotaSellingPrice, model.QuantitySubQuotaSold)
        expr -= pyo.sum_product(model.SuperQuotaSellingPrice, model.QuantitySuperQuotaSold)
        return expr
    model.SecondStageCost = pyo.Expression(rule=ComputeSecondStageCost_rule)

    def total_cost_rule(model):
        if (sense == pyo.minimize):
            return model.FirstStageCost + model.SecondStageCost
        return -model.FirstStageCost - model.SecondStageCost
    model.Total_Cost_Objective = pyo.Objective(rule=total_cost_rule, 
                                               sense=sense)

    return model

# begin helper functions
#=========
def scenario_names_creator(num_scens, start=None):
    # return the full list of num_scens scenario names
    # if start!=None, the list starts with the 'start' labeled scenario
    if (start is None) :
        start=0
    if bunsize == 0:
        return [f"scen{i}" for i in range(start,start+num_scens)]
    else:
        # The hack should have changed the value of num_scens to be a fib!
        # We will assume that start and and num_scens refers to bundle counts.
        # Bundle numbers are zero based and scenario numbers as well.
        return [f"bundle_{i*bunsize}_{(i+1)*bunsize-1}" for i in range(start,start+num_scens)]


#=========
def inparser_adder(cfg):
    # add options unique to farmer
    cfg.num_scens_required()
    cfg.add_to_config("crops_multiplier",
                      description="number of crops will be three times this (default 1)",
                      domain=int,
                      default=1)
    
    cfg.add_to_config("farmer_with_integers",
                      description="make the version that has integers (default False)",
                      domain=bool,
                      default=False)
    cfg.add_to_config("bundle_size",
                      description="number of scenarios per bundle (default 0, which means no bundles, as does 1)",
                      domain=int,
                      default=0)
    

#=========
def kw_creator(cfg):
    # (for Amalgamator): linked to the scenario_creator and inparser_adder
    kwargs = {"use_integer": cfg.get('farmer_with_integers', False),
              "crops_multiplier": cfg.get('crops_multiplier', 1),
              "num_scens" : cfg.get('num_scens', None),
              }
    return kwargs

def sample_tree_scen_creator(sname, stage, sample_branching_factors, seed,
                             given_scenario=None, **scenario_creator_kwargs):
    """ Create a scenario within a sample tree. Mainly for multi-stage and simple for two-stage.
        (this function supports zhat and confidence interval code)
    Args:
        sname (string): scenario name to be created
        stage (int >=1 ): for stages > 1, fix data based on sname in earlier stages
        sample_branching_factors (list of ints): branching factors for the sample tree
        seed (int): To allow random sampling (for some problems, it might be scenario offset)
        given_scenario (Pyomo concrete model): if not None, use this to get data for ealier stages
        scenario_creator_kwargs (dict): keyword args for the standard scenario creator funcion
    Returns:
        scenario (Pyomo concrete model): A scenario for sname with data in stages < stage determined
                                         by the arguments
    """
    # Since this is a two-stage problem, we don't have to do much.
    sca = scenario_creator_kwargs.copy()
    sca["seedoffset"] = seed
    sca["num_scens"] = sample_branching_factors[0]  # two-stage problem
    return scenario_creator(sname, **sca)


# end helper functions


#============================
def scenario_denouement(rank, scenario_name, scenario):
    sname = scenario_name
    #print("denouement needs work")
    #scenario.pprint()
    return
    s = scenario
    if sname == 'scen0':
        print("Arbitrary sanity checks:")
        print ("SUGAR_BEETS0 for scenario",sname,"is",
               pyo.value(s.DevotedAcreage["SUGAR_BEETS0"]))
        print ("FirstStageCost for scenario",sname,"is", pyo.value(s.FirstStageCost))


# special helper function (hack) for bundles
def bundle_hack(cfg):
    # Hack to put bundle information in global variables to be used by
    # the names creator.  (only relevant for bundles)
    # numbuns and bunsize are globals with default value 0
    if cfg.bundle_size > 1:
        assert cfg.num_scens % cfg.bundle_size == 0,\
            "Due to laziness, the bundle size must divide the number of scenarios"
        global bunsize, numbuns, original_num_scens
        bunsize = cfg.bundle_size
        numbuns = cfg.num_scens // cfg.bundle_size
        original_num_scens = cfg.num_scens
        cfg.num_scens = numbuns

        
