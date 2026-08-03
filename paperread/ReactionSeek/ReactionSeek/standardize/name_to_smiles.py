import os
import time
import json

import pandas as pd
import pubchempy as pcp
import openai

from genkai.llm import get_model, install_openai_compat

install_openai_compat(openai)

def pubchem(name):
    try:
        smi = pcp.get_compounds(name, 'name')[0].isomeric_smiles
    except Exception as e:
        return 'Not Found'
    if smi != '':
        return smi
    else:
        return 'Not Found'

def opsin(name):
    with open('input_temp.txt', 'w') as f:
        f.writelines([name])
        f.close()
    os.system('java -jar opsin-cli-2.8.0-jar-with-dependencies.jar -osmi input_temp.txt output_temp.txt')
    with open('output_temp.txt', 'r') as f:
        smi = f.readline()
        f.close()
    if smi != '\n':
        return smi
    else:
        return 'Not Found'

def get_name_from_llama(name, model=None):
    prompt = """
    Please extract the compounds or elements in the following dialogues and tell me their chemical names. You should response the name in a json format like {'name' : 'chemical name'}. The key 'name' is the origin name in the input. The value 'chemical name' is the chemical name of the compound or element. You shouldn't guess the chemical name of the raw name, and you should answer according to the name entered as much as possible. If the name refers to a class of compounds, please give a compound belonging to that class in the value 'chemical name' as an alternative. For example, halogens are replaced by chlorides, and alkyl groups are replaced by ethyl groups. If it is a complex mixture such as petroleum ether or alcohol, the answer should be ' none '.If you are not sure whether your answer is correct, you should answer 'none' in 'chemical name'.

    example:
        input: 
            o- and, predominantly, p-tolunitrile
        answer:
            {
                "o-tolunitrile": "3-Cyanotoluene",
                "p-tolunitrile": "4-Cyanotoluene"
            }

    input: 

    """

    response = openai.ChatCompletion.create(
            model=model or get_model(),
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt + name}
            ],
        )
    result = response.choices[0].message['content']
    json_dic = eval(result)
    return json_dic.values()

def get_smiles(name):
    smi = pubchem(name)
    if smi != 'Not Found':
        return smi
    smi = opsin(name)
    if smi != 'Not Found':
        return smi
    new_name = get_name_from_llama(name)
    smi = pubchem(name)
    if smi != 'Not Found':
        return smi
    smi = opsin(name)
    if smi != 'Not Found':
        return smi
    return 'Not Found'

if __name__ == '__main__':

    start = time.perf_counter()
    input_filename = 'name.csv'# Your input file name.
    output_filename = 'smiles.csv'# Output file name.
    input_data = pd.read_csv(input_filename)
    output_data = pd.DataFrame()
    output_data['Name'] = input_data['Name']
    output_data['SMILES'] = input_data['Name'].apply(get_smiles)
    output_data.to_csv(output_filename, index=False)
    end = time.perf_counter()
    print('runningtime:' + str(end - start))

    
