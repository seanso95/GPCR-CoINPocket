import os
import json
import numpy as np
import pandas as pd
import sys
import getopt
from scipy.optimize import minimize
from sklearn.model_selection import ParameterGrid
from math import sqrt

# detect flags: -n nonpolar -p polar -t algorithm type
opts, args = getopt.getopt(sys.argv[1:], 'n:p:f:t:d:')
for opt, arg in opts:
    if opt in ['-n']:
        NPW = float(arg)
    elif opt in ['-p']:
        POW = float(arg)
    elif opt in ['-f']:
        arg = int(arg)
        if 0 <= arg <= 5:
            EXCL_FOLD = arg
        else:
            sys.exit('error: excluded fold must be between 0 and 4 (or 5 for unfolded)')
    elif opt in ['-t']:
        if arg.lower() in ['nelder-mead', 'cobyla']:
            METHOD = arg
        else:
            sys.exit('error: algorithm must be nelder-mead or cobyla')
    elif opt in ['-d']:
        OUT_FOLDER = arg
    else:
        sys.exit('error: incorrect flag used (-n/-p/-t)')

# set parameters and load dependencies
#OUT_FOLDER = '/home/seanso/cp_optim/out/'
#IN_FOLDER = '/home/seanso/cp_optim/in/'
IN_FOLDER = './in/'
MAX_ITER = 100000

WEIGHTS = (NPW, POW)
# TAB_BCP = pd.read_csv(f'{IN_FOLDER}bcp.csv', keep_default_na=False)
# TAB_ALIG = pd.read_csv(f'{IN_FOLDER}stacked_alig.csv', keep_default_na=False)
# TAB_LABELS = pd.read_csv(
#     f'{IN_FOLDER}labels_twi_fold.csv', keep_default_na=False)
try:
    # TAB_ALIG = pd.read_pickle(f'{IN_FOLDER}/stacked_alig.pkl.zip')
    TAB_LABELS = pd.read_pickle(f'{IN_FOLDER}/labels_twi_fold_ix.pkl.zip')  # ix version needed
    # TAB_PAIRS = pd.read_pickle(f'{IN_FOLDER}/GPCRpairsalig.pkl.zip')
    TAB_PAIRS_LONG = pd.read_pickle(f'{IN_FOLDER}/aaPair_ij_stre_fp.pkl.zip')
    BCP_ARRAY = np.load(f'{IN_FOLDER}/bcp.npy')
except FileNotFoundError:
    import sys
    sys.exit('Dependencies not found - launch code from ./')


def SquarifyMatrix(x, exclude=True):
    """
    Turn input matrix/dataframe into a square.

    When exclude is True, the specified EXCL_FOLD is removed from the dataset.
    This is used when training the weights, calculating ROC AUC from 4 of 5
    folds.
    
    When exclude is False, only EXCL_FOLD is kept. This is used to store a
    record of the 'test' fold AUC for plotting stability of the minimisation.
    """
    cp_scores = x[['pair', 'simAvgP']].copy()
    
    # convert to square
    tmp_tab = cp_scores.copy()
    tmp_tab['pair'] = (tmp_tab['pair'].str.split('@')
                       .map(lambda x: x[::-1] if x[0] != x[1] else '')
                       .map(lambda x: '@'.join(x)))
    cp_scores = pd.concat([cp_scores, tmp_tab.loc[tmp_tab.pair != '']],
                          ignore_index=True)
    
    # merge true/false labels
    cp_scores = pd.merge(left=TAB_LABELS,
                         right=cp_scores,
                         left_on='pairix',
                         right_on='pair')
    
    if exclude:
        # remove excluded fold
        cp_scores = cp_scores.loc[cp_scores.fold != EXCL_FOLD]
    else:
        # keep only specified fold
        cp_scores = cp_scores.loc[cp_scores.fold == EXCL_FOLD]
    
    return cp_scores


def ROC_AUC(in_df):
    """
    Calculate ROC score and scale it to emphasise early positives
    Function written to mimic ICM implementation
    
    input: dataframe generated by CalcCP
    output: 100 - scaled AUC (cost function score), used for minimiser
    """
    in_df['simAvgP'] = -in_df['simAvgP']
    in_df = in_df.sort_values(by='simAvgP')
    
    # account for ranking issues by treating identical scores as group
    dupes = in_df[in_df.duplicated(subset=['simAvgP'], keep=False)]
    grouped_dupes = dupes.groupby('simAvgP')
    if (grouped_dupes['tr'].sum() > 0).any():  # if any group needs averaging
        # average the groups, then replace values in main table
        grouped_avg = grouped_dupes['tr'].mean()
        grouped_avg = grouped_avg[grouped_avg > 0]
        for sim_score, avg_tr in grouped_avg.items():
            in_df.loc[in_df['simAvgP'] == sim_score, 'tr'] = avg_tr
    
    # calculate the scaled AUC
    nof_pts = len(in_df)
    nof_correct = len(in_df[in_df['tr'] > 0.])
    true_pos = (100 * np.cumsum(in_df['tr'])) / nof_correct
    cum_pts_frac = np.asarray([i for i in range(1, nof_pts + 1)]) / nof_pts
    weighted_points = [100 * sqrt(_) for _ in cum_pts_frac]
    x_increments = np.array(weighted_points) - [0., *weighted_points[0:-1]]
    scaled_auc = (0.01 * sum(true_pos * x_increments))
    return scaled_auc


def CalcROC(x):
    """
    call CalcCP() to calculate CP scores
    call SquarifyMatrix() to return square matrix of CP scores
    run weighted AUC calculation
    take 100 - wAUC as return value - minimise this to maximise accuracy

    input argument format: x = ((npw, pow), fold)
    """
    if isinstance(x, pd.DataFrame):
        cp_scores = SquarifyMatrix(x, exclude=False)
    else:
        np_weight, po_weight = x
        bb_weight = 1 - np_weight - po_weight
        weights = (np_weight, po_weight, bb_weight)
        cp_frame = CalcCP(weights)
        cp_scores = SquarifyMatrix(cp_frame, exclude=True)
    
    scaled_auc = ROC_AUC(cp_scores)
    print(f'{scaled_auc}')
    if isinstance(x, np.ndarray):
        WEIGHT_TABLE.append((np_weight, po_weight, bb_weight, scaled_auc))
    
    return 100 - scaled_auc


def CalcCP(x):
    """
    Complete rewrite - create superlarge table with indices and perform a single groupby operation
    """
    
    def Zscore(df):
        """
        Perform Z-score normalisation on column 'sim' of an input DataFrame.
        For use with pd.groupby.DataFrameGroupBy.apply().
        """
        df['same'] = df['i'] - df['j']
        tmp = df[df['same'] < 0]
        mu = tmp['sim'].mean()
        sigma = tmp['sim'].std()
        df.loc[:, 'sim'] = (df['sim'] - mu)/sigma
        return(df.drop('same', axis=1))
    
    # initialise weights
    if len(x) < 3:
        np_weight, po_weight = x
        bb_weight = 1 - np_weight - po_weight
    else:
        np_weight, po_weight, bb_weight = x
    print(f'Optimising: {np_weight}np, {po_weight}po, {bb_weight}bb')
    
    # weight_matrix: 0: backbone, 1: nonpolar, 2: polar
    # 1-scores as scores are difference scores (we want similarities)
    # bcp['auc'] = 1 - (bcp.bb*bb_weight + bcp.np*np_weight + bcp.po*po_weight)
    similarities = 1 - (BCP_ARRAY[0]*bb_weight + BCP_ARRAY[1]*np_weight + BCP_ARRAY[2]*po_weight)
    
    # process pockets
    # one-sided triangular matrix (40470) + self:self comparisons (285)
    tmp_score = TAB_PAIRS_LONG.copy()
    tmp_score['weight'] = similarities[tmp_score['seq'].values.astype(int)]
    tmp_score['sim'] = tmp_score['stre'] * tmp_score['weight']
    tmp_score = tmp_score[tmp_score['seq'] > -1]
    tmp_score.reset_index(drop=True, inplace=True)
    tmp_score_grouped = tmp_score[['i', 'j', 'fp', 'sim']].groupby(['fp', 'i', 'j']).sum().reset_index()
    tmp_score_grouped = tmp_score_grouped.groupby('fp').apply(Zscore)    
    zdf = tmp_score_grouped.reset_index(drop=True).pivot(index=['i', 'j'],
                                                         columns='fp',
                                                         values='sim').reset_index()
    zdf['simAvgP'] = zdf.drop(['i', 'j'], axis=1).mean(axis=1)
    zdf['pair'] = zdf['i'].astype('str') + '@' + zdf['j'].astype('str')
    return(zdf)


# need to set up constraints, ineq means >= 0
cons = ({'type': 'ineq',
         'fun': lambda W: 1 - W.sum()},
        {'type': 'ineq',
         'fun': lambda W: W[0]},
        {'type': 'ineq',
         'fun': lambda W: W[1]})

# bb_weight, np_weight -> initial_weights[0], initial_weights[1]
#   derive po_weight -> 1 - initial_weights.sum()
param_grid = {'npw': np.linspace(0, 1, 11),
              'pow': np.linspace(0, 1, 11)}
initial_weights = ParameterGrid(param_grid)  # generate grid for searching

print(f'Using method: {METHOD.upper()}')
# create variables for saving output
WEIGHT_TABLE = [("np", "po", "bb", "auc")]
SERIAL = ''.join([f'{_:.2f}' for _ in WEIGHTS]).replace('.', '')
if os.path.isfile(f'./out/{METHOD}_cp{SERIAL}_{EXCL_FOLD}_optim.csv') is True:
    sys.exit(
        f'Set {WEIGHTS[0]}, {WEIGHTS[1]}, {1 - sum(WEIGHTS)} already optimised'
    )

# start optimiser
if METHOD.lower() == 'cobyla':
    result = minimize(CalcROC,
                      WEIGHTS,
                      constraints=cons,
                      method='cobyla',
                      options={'rhobeg': 0.2,
                               'disp': True,
                               'maxiter': MAX_ITER})
elif METHOD.lower() == 'nelder-mead':
    result = minimize(CalcROC,
                      WEIGHTS,
                      bounds=[(0, 1), (0, 1)],
                      method='nelder-mead',
                      options={'disp': True,
                               'maxiter': MAX_ITER,
                               'xatol': 0.01})

# serialise results as json and save
result_dict = dict(result)
result_dict['success'] = str(result_dict['success'])
result_dict = {k: v.tolist() if type(v) is np.ndarray
               else v for k, v in result_dict.items()}
result_dict['final_simplex'] = [
    v.tolist() for v in result_dict.get('final_simplex', np.array([]))
]
print(result_dict)

with open(f'{OUT_FOLDER}/{METHOD}_result{SERIAL}_{EXCL_FOLD}.json', 'w') as file:
    json.dump(result_dict, file, indent=4)

# save tracked weights with outputs
with open(f'{OUT_FOLDER}/{METHOD}_log{SERIAL}_{EXCL_FOLD}.txt', 'w') as file:
    contents = [f"{a}, {b}, {c}, {d}\n" for a, b, c, d in WEIGHT_TABLE]
    file.writelines(contents)

# save base CP scores
outfile = CalcCP(
    (WEIGHTS[0], WEIGHTS[1], 1 - sum(WEIGHTS))
)
outfile.to_csv(f'{OUT_FOLDER}/{METHOD}_cp{SERIAL}_{EXCL_FOLD}.csv', index=False)

# save optimised CP scores
outfile = CalcCP(result_dict['x'])
outfile.to_csv(f'{OUT_FOLDER}/{METHOD}_cp{SERIAL}_{EXCL_FOLD}_optim.csv', index=False)

# save test fold wAUC
with open(f'{OUT_FOLDER}/{METHOD}_log{SERIAL}_{EXCL_FOLD}_testfold.txt', 'w') as file:
    file.write(f'{100 - CalcROC(outfile)}')
