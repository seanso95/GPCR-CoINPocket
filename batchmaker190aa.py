import re
import numpy as np

with open('./jobs_190aa.template', 'r') as f:
    contents = f.read()

replace_dict = {
    'REPLACE_NAME': None,
    'REPLACE_NUM': None,
    'REPLACE_FOLD': None,
}

for i in range(380):
    replace_dict['REPLACE_NUM'] = str(i)
    for fold in range(6):
        replace_dict['REPLACE_FOLD'] = str(fold)
        replace_dict['REPLACE_NAME'] = f'nm_{i}_f{fold}_rand'
        rep = dict((re.escape(k), v) for k, v in replace_dict.items())
        pattern = re.compile('|'.join(replace_dict.keys()))
        text = pattern.sub(lambda m: rep[re.escape(m.group(0))], contents)
        with open(f'./jobs_190aa/{replace_dict["REPLACE_NAME"]}.job', 'w') as f:
            f.writelines(text)