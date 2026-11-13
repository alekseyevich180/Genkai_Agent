# ReactionSeek: LLM-Powered Literature Data Mining and Knowledge Discovery in Organic Synthesis

## Project overview
ReactionSeek automates the multi-modal extraction of chemical data from scientific literature. It employs a hybrid architecture that combines the contextual understanding of LLMs with the chemical precision of established cheminformatics tools. ReactionSeek utilizes a domain-specific prompt engineering strategy, enabling robust and accurate data mining without the need for resource-intensive model fine-tuning.

## Table of contents

· [Getting started](#getting-started)

· [Automatically collecting reaction data](#automatically-collecting-reaction-data)

· [SynChat](#synchat)

· [Contributing](#contributing)

· [License](#license)

· [Contact](#contact)

## Getting started

Clone the repository by using
```
https://github.com/DeepSynthesis/ReactionSeek.git
 ```

Then using:
```
cd ReactionSeek
conda create -n ReactionSeek python=3.12.0
conda activate ReactionSeek
pip install -r requirements.txt
```
to create a conda environment and install all the dependencies.

<!-- then see [reaction_data_collection_automatically](ReactionSeek/reaction_data_collection_automatically.md) to run the program. -->

## Automatically collecting reaction data

### extract_gpt.py
This script is used to extract reaction data using OpenAI API foramt. The script input should be a json file at least contains `Title` and `Procedure`, for example:

```json
{
    "volume96article1": {
        "Title": "Title information of the reaction procedure.",
        "Procedure": "The reaction of 1,2-dimethoxyethane with sodium ethoxide in dry ether is an elimination reaction to form ethene and methoxide ion."
    },
}
```

After prepared your input files, you should edit this part of script:

```python
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
```

Then run the script:

```bash
python extract_gpt.py
```

### strcuturelize.py
This script is used to structurelize the initial output csv file to a csv table containing Index, Reactants, Reactant amounts, Products, Product amounts, Solvents, Reaction temperature, Reaction time and Yield. The input file should be the output csv file of extract_gpt.py. 

After prepared your input files, you should edit this part of script:

```python
if __name__ == '__main__':
    volumes = ["Volume96-100"]#your json name(same as the first step)
    start = time.perf_counter()
    main(volumes)
    end = time.perf_counter()
    print('runningtime:' + str(end - start))
```

Then run the script:

```bash
python strcuturelize.py
```

The output file "xxx_table.csv" is the structured csv file.

### name_to_smiles.py
This script is a part of standardization module, used to convert the names of reactants and products to smiles. The input file should be a csv file containing a `Name` column.

After prepared your input files, you should edit this part of script to change your file path:

```python
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
```

Then run the script:

```bash
python name_to_smiles.py
```
The output file "smiles.csv" is the csv file containing the smiles of each name.


### time_standardlize.py
This script is a part of standardization module, used to standardize the reaction time. The input file should be a csv file containing an `Index` and a `Reaction time` column.

After prepared your input files, you should edit this part of script to change your file path and your model API:

```python
if __name__ == '__main__':
    openai.proxy = {
                    'http': '',# Your http proxy
                    'https': ''# Your https proxy
    }
    openai.api_key = ""# Your api key
    volumes = ["Volume16-20"]# Your input file name
    delay = 20# Your delay time. If you don't have rate limit, please change it.
    model = "gpt-3.5-turbo"# Your model name
    start = time.perf_counter()
    main(volumes, delay, model)
    end = time.perf_counter()
    print('runningtime:' + str(end - start))
```
Then run the script:

```bash
python time_standardlize.py
```

The output file "xxx_timetable.csv" is the standardized csv file.

## SynChat
[SynChat](http://gpu1.luoszgroup.com:18501/) is an interactive tool powered by LLM agents. SynChat allows researchers to query the historical reaction data and associated metadata using natural language, providing a more intuitive and efficient means of accessing specific data compared to traditional search methodology.

## Contributing
We welcome contributions from the community. Please fork the repository and submit pull requests.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contact
If you have any questions or suggestions, please contact us at lijiawei24@mails.tsinghua.edu.cn.