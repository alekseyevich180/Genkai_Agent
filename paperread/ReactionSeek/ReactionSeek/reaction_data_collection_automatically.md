# Automatically collecting reaction data

## extract_gpt.py
This script is used to extract reaction data using OpenAI API foramt. The script input should be a json file at least contains "Title" and "Procedure", for example:

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

## strcuturelize.py
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

## name_to_smiles.py
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

## time_standardlize.py
## time_standardlize.py
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