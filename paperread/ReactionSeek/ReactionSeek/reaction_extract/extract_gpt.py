# -*- coding: UTF-8 -*-
# the first step for the data collection
import openai
import os
import time
import json
import pandas as pd
from pathlib import Path
import sys

for _parent in Path(__file__).resolve().parents:
    if (_parent / "genkai_api_config.py").is_file():
        sys.path.insert(0, str(_parent))
        break
from genkai_api_config import get_model, install_openai_compat

install_openai_compat(openai)

def get_completion(prompt, model=None):
    '''
        get completion from OpenAI.
    '''
    messages = [{'role': 'user', "content": prompt}]
    response = openai.ChatCompletion.create(
        model=model or get_model(),
        messages=messages,
        temperature=0
    )
    return response.choices[0].message['content']

def get_names(title, text, model=None):
    '''
    get information from reaction procedures.
    Input: title and procedure string.
    Output: a string containing a table of information.
    '''
    
    
    prompt = f"""
    You will be given a reaction title and a synthesis procedure. Please summarize the following details in a table: Reactants, Reactant amounts, Products, Product amounts, solvents, reaction temperature, reaction time and yield. If any information is not provided or you are unsure, use "N/A" in the cell.   

    If multiple reactions are provided, use multiple rows to represent them. If multiple units or components are provided for the same factor (e.g. g and mol for the weight, multiple linker or metals, multiple temperature and reaction time, mixed solvents, etc.), include them in the same cell and separate by comma.
    If multiple Reactants, Reactant amounts, Products, Product amounts, reaction temperature, reaction time are present, separate them using a comma in the same cell.
    Output table should have 8 columns: | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |

    Some advice to find amount, reaction temperature, reaction time and yield.
    The amount often consists of numbers and units and is not far from the corresponding compound.
    Solvent should only include the solvents of the reaction process, and should not include the solvents added in the washing, recrystallization and other processes.
    Reaction temperature indicates the temperature at which the main reaction is taking place. The reaction temperature is generally numerical, but expressions such as reflux and heat are also expressions of reaction temperature.
    Reaction time is the time during which the reaction takes place, generally in the second half of the description of the reaction conditions, before the product description.
    Yield is the ratio of the actual amount of product produced to the theoretical yield, and is often labeled near the yield of the product. The yield is often a percentage.

    Example 1:
    Title:<'''ALKYL AND ALKYLENE BROMIDES'''>
    Procedure:<'''A given primary alcohol is treated with 25 per cent excess of aqueous (48 per cent) hydrobromic acid (Note 1) together with sulfuric acid (Note 2). The mixture is refluxed (Note 3) in order to convert the alcohol as completely as possible into the corresponding bromide, and the latter is then removed from the reaction mixture by distillation. The water-insoluble layer is separated; washed successively with water, cold concentrated sulfuric acid (Note 4), and a sodium carbonate solution; separated; dried with calcium chloride (Note 5); and distilled. Slight variations from this procedure depend upon the physical and chemical properties of the alcohol used, or of the bromide formed in the reaction. For example, in the preparations of ethyl and allyl bromides, the reaction mixture is not refluxed because of the volatility of the former compound, and because of the chemical reactivity of the latter; in the preparation of iso-amyl bromide, too large a proportion of sulfuric acid may produce appreciable decomposition, whereas halides of high molecular weight, because of their low volatility, are separated from the reaction mixture mechanically, instead of by distillation.\nThe use of a modified sodium bromide-sulfuric acid method (Note 6) for the preparation of alkyl bromides is described in connection with the preparation of n-butyl bromide. This method has been used also for the preparations of iso-amyl and trimethylene bromides, but, in general, the yields were found to be somewhat lower than those obtained with the hydrobromic-sulfuric acid method.'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | Primary alcohol, aqueous hydrobromic acid, sulfuric acid | N/A | Corresponding alkyl bromide | N/A | water | Reflux | N/A | N/A |

    Example 2:
    Title:<'''ALKYL AND ALKYLENE BROMIDES'''>
    Procedure:<'''DOI: 10.15227/orgsyn.001.0003\n(B) iso-AMYL BROMIDE, (CH3)2CHCH2CH2Br\n[Butane, 1-bromo-3-methyl-]\nIn a 5-l. round-bottomed flask, a hydrobromic acid solution is prepared (p. 26) by passing sulfur dioxide into a mixture of 1100 g. of crushed ice and 1 kg. (314 cc., 6.25 moles) of bromine. This is equivalent to a mixture of 2.1 kg. (12.5 moles) of 48 per cent hydrobromic acid and 600 g. of concentrated sulfuric acid. There are then added, in the order mentioned, 880 g. (1086 cc., 10 moles) of iso-amyl alcohol (b.p. 130\u2013132\u00b0) and 100 g. (54.5 cc.) of concentrated sulfuric acid. The clear homogeneous solution is refluxed gently during a period of five to six hours. Even during the early stages of the heating, the separation of iso-amyl bromide is observed, and the reaction appears to be complete after about one hour. The product is isolated as in the preparation of n-butyl bromide below.\nA yield of 1435 g. of crude product is obtained. After purification with concentrated sulfuric acid the product weighs 1410 g. (93 per cent of the theoretical amount). Upon fractionation, however, it is found that appreciable amounts of a high-boiling product are present, and therefore the yield of fractionated material boiling over the range 116\u2013120\u00b0 varies in different experiments from 1330 to 1360 g. (88\u201390 per cent of the theoretical amount).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | iso-amyl alcohol, hydrobromic acid, sulfuric acid | 880 g (10 moles), 2.1 kg (12.5 moles), 100 g | iso-amyl bromide | 1330-1360 g | hydrobromic acid | reflux | 5-6 hours | 88-90% |
    
    Example 3:
    Title:<'''4-METHYLESCULETIN'''>
    Procedure:<'''A smooth, uniform paste is made by thoroughly mixing 60 g. (0.45 mole) of ethyl acetoacetate (p. 235) (Note 1) and 114 g. (0.45 mole) of hydroxyhydroquinone triacetate (p. 317). This requires several minutes of stirring. To this mixture is added 450 cc. of 75 per cent sulfuric acid (Note 2). The paste slowly dissolves with the evolution of heat, giving a deep red solution; the latter is heated on a warm bath with occasional stirring until it reaches 80\u00b0, at which temperature it is maintained for one-half hour. It is then allowed to cool to room temperature and poured into 1850 cc. of cold water. The resulting mixture is cooled to room temperature, filtered with suction, and the precipitate washed with cold water to free it from excess acid. The 4-methylesculetin thus obtained is dried at 100\u00b0 and is generally gray in color. The yield is about 80 g. (92 per cent of the theoretical amount).\nA pure product may be obtained by dissolving, with the aid of heat and stirring, 100 g. of 4-methylesculetin in a solution of 200 g. of borax in 700 cc. of water. The solution obtained is filtered while hot and then cooled, whereupon the esculetin borate separates (Note 3). This is filtered off and dissolved in 1800 cc. of water, and the solution thus obtained added to 50 g. (27.2 cc.) of concentrated sulfuric acid in 500 cc. of water. 4-Methylesculetin separates and, after the mixture has been cooled, is filtered, washed, and dried. From 100 g. of the crude material, 85 g. of pure product melting at 272\u2013274\u00b0 (uncorr.) is obtained. This is generally nearly colorless but occasionally possesses a slight grayish tinge.'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | ethyl acetoacetate, hydroxyhydroquinone triacetate, sulfuric acid | 60 g (0.45 mole), 114 g (0.45 mole), 450 cc | 4-methylesculetin | 80 g | sulfuric acid | 80°C | 30 minutes | 92% |
    
    Example 4:
    Title:<'''2-BUTYN-1-OL'''>
    Procedure:<'''In a 3-l. three-necked round-bottomed flask fitted with a reflux condenser and a mercury-sealed stirrer, 250 g. (2 moles) of 1,3-dichloro-2-butene (Note 1) and 1.25 l. of 10% sodium carbonate are heated at reflux temperature for 3 hours. The 3-chloro-2-buten-1-ol is extracted with three 300-ml. portions of ether, which are then dried over anhydrous magnesium sulfate. The ether is removed by distillation through a 20-cm. Fenske column, and the residue is distilled from a 250-ml. Claisen flask, yielding 134 g. (63%) of 3-chloro-2-buten-1-ol, b.p. 58\u201360\u00b0/8 mm., n20D 1.4670.\nA solution of sodium amide in liquid ammonia is prepared according to the procedure described on p. 763 using a 4-l. Dewar flask equipped with a plastic cover (Note 2) and a mechanical stirrer. Anhydrous liquid ammonia (3 l.) is introduced through a small hole in the plastic cover, and 1.5 g. of hydrated ferric nitrate is added followed by 65 g. (2.8 g. atoms) of clean, freshly cut sodium. The mixture is stirred until all the sodium is converted into sodium amide, after which 134 g. (1.26 moles) of 3-chloro-2-buten-1-ol is added over a period of 30 minutes. The mixture is stirred overnight, then 148 g. (2.8 moles) of solid ammonium chloride is added in portions at a rate that permits control of the exothermic reaction. The mixture is transferred to a metal bucket (5-l., preferably of stainless steel) and allowed to stand overnight in the hood while the ammonia evaporates. The residue is extracted thoroughly with five 250-ml. portions of ether, which is removed by distillation through a 20-cm. Fenske column. Distillation of the residue yields 66\u201375 g. (75\u201385%) of 2-butyn-1-ol, b.p. 55\u00b0/8 mm., n20D 1.4550 (Note 3).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | 3-chloro-2-buten-1-ol, sodium, ammonium chloride | 134 g (1.26 moles), 65 g (2.8 g atoms), 148 g (2.8 moles) | 2-butyn-1-ol | 66-75 g | water | liquid ammonia | overnight | 75-85% |

    Example 5:
    Title:<'''1,4-CYCLOHEXANEDIONE'''>
    Procedure:<'''2,5-Dicarbethoxy-1,4-cyclohexanedione. A solution of sodium ethoxide is prepared by adding small pieces of sodium (92 g., 4 g. atoms) as rapidly as possible to 900 ml. of commercial absolute ethanol contained in a 3-l., three-necked, round-bottomed flask equipped with two stoppers and a reflux condenser fitted with a drying tube packed with calcium chloride and soda lime. The reaction is completed by heating the mixture under reflux for 3\u20134 hours (Note 1). To the hot solution is added diethyl succinate (348.4 g., 2 moles) (Note 2) in one portion (Caution! Exothermic reaction), and the mixture is heated under reflux by maintaining the original bath temperature for 24 hours. A thick pink-colored precipitate is formed almost immediately and remains throughout the reaction.\nAt the end of the 24-hour period, the ethanol is removed under reduced pressure on a steam bath. A 2N sulfuric acid solution (2 l.) is added to the warm residue, and the mixture is stirred vigorously for 3\u20134 hours (Note 3). The solid is removed by suction filtration and washed several times with water. The air-dried product is a pale-buff powder weighing 180\u2013190 g., m.p. 126\u2013128\u00b0. The solid is added to 1.5 l. of ethyl acetate, the mixture is heated to boiling and is filtered rapidly while hot (Note 4). The filtrate is chilled, and it yields cream to pink-cream colored crystals of 2,5-dicarbethoxy-1,4-cyclohexanedione, 160\u2013168 g., m.p. 126.5\u2013128.5\u00b0. The filtrate is concentrated to one-tenth of its original volume in order to obtain a second crop of crystals, 5\u20137 g., m.p. 121\u2013125\u00b0. The total yield is 165\u2013175 g. (64\u201368%).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | sodium, ethanol, diethyl succinate | 92 g (4 g atoms), 900 ml, 348.4 g (2 moles) | 2,5-dicarbethoxy-1,4-cyclohexanedione | 160-168 g | ethanol | reflux | 24 hours | 64-68% |

    Example 6:
    Title:<'''3-BENZYL-3-METHYLPENTANOIC ACID'''>
    Procedure:<'''B. Ethyl 3-benzyl-2-cyano-3-methylpentanoate. A 2-l. three-necked round-bottomed flask, fitted with a tantalum wire Hershberg stirrer, a condenser, and a separatory funnel, is arranged for use of a nitrogen atmosphere.2 Magnesium (19.2 g., 0.79 g. atom) and 100 ml. of dry ether3 are placed in the flask, and a solution of 100 g. (91 ml., 0.79 mole) of benzyl chloride in 500 ml. of dry ether is added in a period of 1.5\u20132.0 hours, with stirring, while the mixture boils spontaneously. The mixture is boiled for 15 minutes after completion of the addition, then a solution of 110 g. (0.66 mole) of ethyl sec-butylidenecyanoacetate in 130 ml. of benzene is added over a 30-minute period with spontaneous reflux. The reaction mixture is stirred and heated under reflux for an additional hour. A precipitate separates after about 30 minutes.\nThe reaction mixture is poured onto about 400 g. of cracked ice and is made acidic with 20% sulfuric acid. After two clear phases have formed the mixture is poured into a separatory funnel, and the lower layer is removed. This aqueous layer is extracted with two 100-ml. portions of benzene and discarded. The three organic extracts are washed separately and successively with 125 ml. of water and 125 ml. of saturated sodium chloride solution, then filtered successively through a layer of anhydrous sodium sulfate.\nThe combined extract (about 1 l.) is flash-distilled at atmospheric pressure from a 250-ml. Claisen flask. After the solvent and a small amount of fore-run (ca. 15 g., b.p. 45\u00b0/3 mm.) have been removed, the product is distilled to yield 157\u2013162 g. (92\u201395%), b.p. 150\u2013162\u00b0/3 mm. (bath temperature, 180\u2013190\u00b0), nD25 1.5053\u20131.5063 (Note 5), (Note 6), and (Note 7).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | Magnesium, benzyl chloride, ethyl sec-butylidenecyanoacetate | 19.2 g (0.79 g atom), 100 g (91 ml, 0.79 mol), 110 g (0.66 mole) | Ethyl 3-benzyl-2-cyano-3-methylpentanoate | 157-162 g | ether | Boiling, reflux | 1.5-2.0 hours, 15 minutes, 30 minutes, 1 hour | 92-95% |

    Example 7:
    Title:<'''p-CHLOROPHENYL ISOTHIOCYANATE'''>
    Procedure:<'''In a 250-ml. round-bottomed flask fitted with mechanical stirrer, reflux condenser, and thermometer are placed 38.3 g. (0.30 mole) of p-chloroaniline (Note 1), 41 ml. (0.6 mole) of concentrated aqueous ammonia (sp. gr. 0.9), and 21 ml. (0.35 mole) of carbon disulfide. The mixture is stirred vigorously, and when it is heated to 30\u00b0 the reaction starts. The temperature is maintained at 30\u201335\u00b0 by external cooling (Note 2). The reaction mixture turns into a deep-red turbid solution within a few minutes, and then suddenly a heavy yellow precipitate of ammonium p-chlorophenyldithiocarbamate separates. To the mixture 15 ml. of water is added, and stirring is continued for 1 hour. The mixture is filtered with suction, and the residue is washed with two 30-ml. portions of a 3% aqueous solution of ammonium chloride and with two 15-ml. portions of 96% ethanol.\nThe ammonium p-chlorophenyldithiocarbamate obtained is transferred immediately to a 1-l. beaker fitted with an efficient mechanical stirrer. Water (250 ml.) is added, and the temperature is raised to 30\u00b0. A solution of 28.4 g. (0.30 mole) of chloroacetic acid in 30 ml. of water is neutralized with sodium carbonate [18.6 g. (0.15 mole) of Na2CO3\u00b7H2O in 70 ml. of water] and is added to the well-stirred dithiocarbamate suspension over a 10-minute period (Note 3). In the beginning the suspension gradually becomes less viscous, but at the end of the addition it rapidly turns into a creamy mass. Another 250 ml. of water is added to facilitate stirring, which is continued for 1 hour after the addition at about 30\u00b0.\nThe creamy suspension is allowed to cool to room temperature, and the electrodes of a pH meter are inserted (Note 4). A solution of 20.5 g. (0.15 mole) of zinc chloride (Note 5) in 75 ml. of water is added dropwise with vigorous stirring over a period of 45 minutes, while the pH is maintained at 7 by the simultaneous dropwise addition of a 4N aqueous solution of sodium hydroxide (Note 6). The mixture is stirred for 1 hour and is then filtered with suction; the solid product is dried under reduced pressure over phosphorus pentoxide. The dry material is slurried with 200 ml. of petroleum ether (b.p. 30\u201360\u00b0), and the solvent is decanted. This process is repeated five times, and the combined extract is evaporated at reduced pressure. The yield of almost pure p-chlorophenyl isothiocyanate, obtained as a readily crystallizing oil with a pleasant anise-like odor, is 33\u201335 g. (65\u201368%), m.p. 44\u201345\u00b0. The product can be recrystallized from the minimum amount of ethanol at 50\u00b0.'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | ammonium p-chlorophenyldithiocarbamate, chloroacetic acid, sodium carbonate, zinc chloride | N/A, 28.4 g (0.30 mole), 18.6 g (0.15 mole), 20.5 g (0.15 mole) | p-chlorophenyl isothiocyanate | 33-35 g | concentrated aqueous ammonia | room temperature | N/A | 65-68% |

    Example 8:
    Title:<'''Synthesis of N-Acyl Pyridinium-N-Aminides and Their Conversion to 4-Aminooxazoles via a Gold-Catalyzed Formal (3+2)-Dipolar Cycloaddition'''>
    Procedure:<'''A. ((tert-Butoxycarbonyl)glycyl)(pyridin-1-ium-1-yl)amide (2). A 500 mL single-necked, round-bottomed flask equipped with a 3 cm stirrer bar and a needle-pierced septum is charged with methyl (tert-butoxycarbonyl)-glycinate 1 (Note 2) (6.80 g, 36.0 mmol, 1.20 equiv) and methanol (Note 3) (225 mL). 1-Amino pyridinium iodide (Note 4) (6.67 g, 30.0 mmol) is added and the reaction is stirred for 5 min at 22 \u00b0C. Potassium carbonate (Note 5) (9.95 g, 72.0 mmol, 2.40 equiv) is added and the reaction is stirred at 22 \u00b0C for 64 h (Note 6) (the yellow heterogeneous reaction turns colorless two seconds after the addition of potassium carbonate, and forms a dark purple solution, Figure 1). After removal of the stir bar, 200 mL of the methanol is removed under reduced pressure (200 mmHg to 70 mmHg, 40 \u00b0C) to give a brown-purple syrup, which is poured onto an alumina pad (Notes 7 and 8).\nFigure 1. Change in reaction color: a) Reaction mixture before potassium carbonate addition; b) Reaction mixture 10 seconds after potassium carbonate addition; c) Reaction mixture after 64 h\nThe flask is rinsed with 10 mL of dichloromethane as well as 50 mL of eluent (dichloromethane-methanol, 9:1), and the product is eluted with 1.1 L of dichloromethane-methanol (9:1) (Note 9). The filtrate is concentrated (375 mmHg to 75 mmHg, 40 \u00b0C) and then transferred to a 500 mL single-necked round-bottomed flask and rinsed with dichloromethane (20 mL). The filtrate is concentrated further (375 mmHg to 15 mmHg, 40 \u00b0C) and then dried under vacuum (0.08 mmHg, 20 \u00b0C, 1 h) to give a brown powder (Note 10). A 3 cm Teflon coated stirrer bar is added, followed by acetone (175 mL) (Note 11). A water-cooled condenser is added to the flask and the mixture is heated to reflux until complete dissolution had occurred (15 min). The mixture is allowed to cool to room temperature over 3 h and then cooled to -22 \u00b0C in a freezer for 20 h. The resultant fine brown crystals are filtered off through a sintered S3 funnel, the flask is rinsed with diethyl ether (Note 12) (3 x 25 mL), and the contents were then added to the funnel.\nFigure 2. Compound 2 after recrystallization from acetone\nThe powder is transferred to a 50 mL single-necked flask and dried under static vacuum (0.12 mmHg, 18 h) (6.39 g, 85%, 98% purity) (Figure 2) (Notes 13, 14, and 15).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | methyl (tert-butoxycarbonyl)-glycinate, 1-amino pyridinium iodide, methanol, potassium carbonate | 6.80 g (36.0 mmol), 6.67 g (30.0 mmol), 225 mL, 9.95 g (72.0 mmol) | ((tert-Butoxycarbonyl)glycyl)(pyridin-1-ium-1-yl)amide | 6.39 g | methanol | 22°C | 64 hours | 85% |

    Example 9:
    Title:<'''SYNTHESIS OF CHIRAL (E)-CROTYLSILANES: [3R- AND 3S-]-(4E)-METHYL 3-(DIMETHYLPHENYLSILYL)-4-HEXENOATE'''>
    Procedure:<'''C. (3R)-1-(Dimethylphenylsilyl)-1-buten-3-ol (3c) . Acetate (R)-3b (9.0 g, 36.27 mmol) is dissolved under a nitrogen atmosphere in a cooled (0\u00b0C), 1-L, round-bottomed flask containing 120 mL of anhydrous Et2O (Note 13). To this stirred mixture is slowly added over 10 min 1.81 g (47.79 mmol, 1.3 eq) of lithium aluminum hydride (LiAlH4). After 15 min, aqueous 5% hydrochloric acid is added dropwise until bubbling ceases (Note 13). The resulting suspension is further diluted with a total volume of 100 mL of the acidic solution. The layers are separated, and the aqueous layer is extracted with 100 mL of Et2O . The combined organic extracts are washed with an aqueous saturated solution of sodium chloride and dried over anhydrous magnesium sulfate , filtered, and concentrated under vacuum, to yield 6.27 g (30.42 mmol, 83%) of the (R)-alcohol 3c. No additional purification is performed (Note 14).'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | Acetate (R)-3b, lithium aluminum hydride | 9.0 g (36.27 mmol), 1.81 g (47.79 mmol) | (3R)-1-(Dimethylphenylsilyl)-1-buten-3-ol | 6.27 g (30.42 mmol) | Et2O | 0°C | 15 min | 83% |
    
    Example 10:
    Title:<'''p-BROMOMANDELIC ACID'''>
    Procedure:<'''B. p-Bromomandelic acid. In a Waring-type blender are placed 89 g. (0.25 mole) of p,\u03b1,\u03b1-tribromoacetophenone and 100\u2013150 ml. of cold water. The mixture is stirred for 10\u201315 minutes, and the contents are transferred to a 1-l. wide-mouthed bottle. The mixing vessel is rinsed with 150\u2013200 ml. of ice-cold water. The material from the rinse is combined with the mixture in the bottle, and sufficient crushed ice is added to bring the temperature below 10\u00b0. One hundred milliliters of a chilled aqueous solution containing 50 g. of sodium hydroxide is added slowly while the bottle is rotated (Note 7). The contents are stored for approximately 4\u20135 days in a refrigerator (5\u00b0) and are shaken occasionally. During this time most of the solid dissolves, but a slight amount remains as a yellow sludge and the liquid assumes a yellow to amber color. The mixture is filtered, and the insoluble material is discarded. An excess of concentrated hydrochloric acid is added to the filtrate. The entire resulting mixture containing a white solid is extracted with three 200-ml. portions of ether. The ether extracts are combined, dried over anhydrous sodium sulfate, and filtered into a 1-l. flask. The ether is carefully removed by distillation using a hot-water bath to give a yellow oil which solidifies when cooled. The product is recrystallized from 500 ml. of benzene. The crystals are collected by filtration and washed with benzene until the filtrate is colorless. The air-dried product (Note 8) weighs 40\u201348 g. (69\u201383% based on p,\u03b1,\u03b1-tribromoacetophenone), m.p. 117\u2013119\u00b0 (Note 9). A second recrystallization from 500 ml. of benzene is sometimes necessary.'''>
    Answer:
    | Reactants | Reactant amounts | Products | Product amounts | Solvents | Reaction temperature | Reaction time | Yield |
    |-----------|-----------------|----------|-----------------|-----------|----------------------|----------------|-------|
    | p,α,α-tribromoacetophenone, sodium hydroxide, hydrochloric acid | 89 g (0.25 mole), 50 g, N/A | p-Bromomandelic acid | 40-48 g | water | 10°C | 4-5 days | 69-83% |
    /////
    Title:<'''{title}'''>
    Procedure:<'''{text}'''>
    """
    response = get_completion(prompt, model=model)
    print(response)
    return response

def main(volumes, model='gpt-3.5-turbo-16k'):
    error = []
    for filename in volumes:
        
        df = pd.DataFrame([{'Index': 0, 'Summary': ''}], index=None)
        error = []
        with open(filename + '.json') as f:
            data = json.load(f)
            f.close()
        for item in data.items():
            input_strs = item[1]["Procedure"]
            input_title = item[1]["Title"]
            itr = 1
            for input_str in input_strs:
                time.sleep(20)#if you don't have rate limit, please change it.
                try:
                    response = get_names(input_title, input_str, model=model)
                    df.loc[len(df)] = [str(item[0]) + '_' + str(itr), response]
                except Exception as e:
                    error.append(str(item[0])+'_' + str(itr)+':' +str(e))
                    error.append('\n')
                    print(filename + ':' + str(item[0]))
                itr = itr + 1
            

        df.to_csv(filename + '_summary.csv', index=None)
        with open(filename + '_names_error.txt','w') as f:
            f.writelines(error)
            f.close()


if __name__ == '__main__':

    openai.proxy = {
                    'http': '',#your http proxy
                    'https': ''#your https proxy
    }
    openai.api_key = ""#your api key
    openai.base_url = "https://api.openai.com/v1"#your api base url
    model = 'gpt-3.5-turbo-16k'#your model
    volumes = ["Volume26-30"]#names of json files
    start = time.perf_counter()
    main(volumes, model)
    end = time.perf_counter()
    print('runningtime:' + str(end - start))


