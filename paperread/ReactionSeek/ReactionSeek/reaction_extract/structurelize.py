# -*- coding: UTF-8 -*-
# the second step for the data collection
import pandas as pd
import time



def tabulate_condition(df):
    '''
    change the table string into a dataframe.
    '''
    columns = ['Index', 'Reactants', 'Reactant amounts', 'Products', 'Product amounts', 'Solvents', 'Reaction temperature', 'Reaction time', 'Yield'] # Initialize an empty dataframe with the desired columns
    result_df = pd.DataFrame(columns=columns)
    for i, row in df.iterrows():
        summarized = str(row['Summary'])
        index = str(row['Index'])
        if "|" in summarized: # Check if the "|" symbol is present in the text string
            # Split the text string into lines and remove the header
            lines = summarized.strip().split("\n")[2:]
            # Iterate through the lines and extract the data
            i = 1
            for line in lines:
                indexed_data = [index + '_' + str(i)]
                data = [x.strip() for x in line.split("|")[1:-1]]
                indexed_data = indexed_data + data
                if len(indexed_data) == len(columns):
                    result_df = pd.concat([result_df, pd.DataFrame([indexed_data], columns=columns)], ignore_index=True) 
                i = i + 1
    return result_df
def main(volumes):
    for filename in volumes:
        df = pd.read_csv(filename + '_summary.csv')
        df2 = tabulate_condition(df)
        df2.to_csv(filename + '_table.csv', index=None)

if __name__ == '__main__':
    volumes = ["Volume96-100"]#your json name(same as the first step)
    start = time.perf_counter()
    main(volumes)
    end = time.perf_counter()
    print('runningtime:' + str(end - start))