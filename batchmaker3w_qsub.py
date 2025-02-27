import re
import numpy as np
from sklearn.model_selection import ParameterGrid

with open('./jobs_3w.template', 'r') as f:
    contents = f.read()

param_grid = {'npw': np.linspace(0, 1, 11),
              'pow': np.linspace(0, 1, 11)}
initial_weights = ParameterGrid(param_grid)  # generate grid for searching

replace_dict = {
    'REPLACE_NAME': None,
    'REPLACE_NONPOLAR': None,
    'REPLACE_POLAR': None,
    'REPLACE_FOLD': None,
    'REPLACE_METHOD': None
}

for method in ['nelder-mead', 'cobyla']:
    replace_dict['REPLACE_METHOD'] = method
    for weights in initial_weights:
        replace_dict['REPLACE_NONPOLAR'] = str(weights['npw'])
        replace_dict['REPLACE_POLAR'] = str(weights['pow'])
        for fold in range(0, 6):
            replace_dict['REPLACE_FOLD'] = str(fold)
            replace_dict['REPLACE_NAME'] = '_'.join([
                f'{method}',
                ''.join(
                    [f'{_:.2f}' for _ in weights.values()]
                ).replace('.', ''),
                f'{fold}'
            ])
            rep = dict((re.escape(k), v) for k, v in replace_dict.items())
            pattern = re.compile('|'.join(replace_dict.keys()))
            text = pattern.sub(lambda m: rep[re.escape(m.group(0))], contents)
            with open(f'jobs_3w/{replace_dict["REPLACE_NAME"]}.qsub', 'w') as f:
                f.writelines(text)
