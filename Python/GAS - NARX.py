# Code-only file for modelling the Gas data



# Configuration
Ntt = 600 # Test-train split
enable_detrend = False 
enable_normalize=True
Q = 4 # Order of ARX Model
 



# Import libraries
import numpy as np
from numpy import genfromtxt
from numpy import linalg as lin
from matplotlib import pyplot as plt
from sklearn.decomposition import PCA
from sklearn.preprocessing import normalize
from sklearn import linear_model
from sklearn import svm
from scipy.signal import savgol_filter
import seaborn as sns
import pandas as pd
from statsmodels.tsa.holtwinters import SimpleExpSmoothing
#from sklearn.gaussian_process import GaussianProcessRegressor
#from sklearn.gaussian_process.kernels import RBF, WhiteKernel, DotProduct, ConstantKernel

# GPyTorch stuff
import torch
import gpytorch


# Import my own modules
import sys
sys.path.insert(0, '..')
from manifolds import embed
from signals import maimpute

# Import data
my_data = genfromtxt('../Data/natgas.data.csv', delimiter=',',dtype='f8')
my_data = my_data[1:,1:] # Ignore the first row, which contains headers
names = ["STOCKS","HDD_FORE","CDD_FORE","JFKTEMP","CLTTEMP","ORDTEMP","HOUTEMP","LAXTEMP","NXT_CNG_STK"]


# Delete the unused features
X = my_data[0:Ntt,:]
X = np.delete(X,1,axis=1)
X = np.delete(X,1,axis=1)
Xnames = ["STOCKS","JFKTEMP","CLTTEMP","ORDTEMP","HOUTEMP","LAXTEMP","NXT_CNG_STK"]
X2 = my_data[Ntt:,:]
X2 = maimpute(X2)
X2 = np.delete(X2,1,axis=1)
X2 = np.delete(X2,1,axis=1)


# Deseasonalize the data
window_length = 13
polyorder = 2
if enable_detrend:
    datatrend  = savgol_filter(X[:,1:10], window_length, polyorder, axis=0)
    X[:,1:10]  = X[:,1:10] - datatrend
    datatrend2 = savgol_filter(X2[:,1:10], window_length, polyorder, axis=0)
    X2[:,1:10] = X2[:,1:10] - datatrend2


# Normalize the input predictors and target
if enable_normalize:
    X  = normalize(X, axis=0)
    X2 = normalize(X2, axis=0)

# Delay embed all of our data. The last column will be our target
Z = np.empty((X.shape[0]-Q+1,Q*X.shape[1] ))
Z2 = np.empty((X2.shape[0]-Q+1,Q*X2.shape[1]))
for k in range(0,X.shape[1]):
    Z[:,np.arange(0,Q) + k*Q] = embed(X[:,k],Q,1)
    Z2[:,np.arange(0,Q) + k*Q] = embed(X2[:,k],Q,1)
#Z[:,Q*X.shape[1] ] = np.mod(np.transpose(np.arange(0,Z.shape[0])),52)
#Z2[:,Q*X.shape[1] ] = np.mod(Ntt+np.transpose(np.arange(0,Z2.shape[0])),52)


# Separate target and predictors
y = Z[:,Z.shape[1]-1]  
Z = Z[:,0:Z.shape[1]-1]
#Z = np.delete(Z,Z.shape[1]-1,axis=1)
y2 = Z2[:,Z2.shape[1]-1]  
Z2 = Z2[:,0:Z2.shape[1]-1]
#Z2 = np.delete(Z2,Z2.shape[1]-1,axis=1)




# Initialize matrix of predictions
NoModels = 5 # No. of models that I will have
Yp = 0*np.empty((y.shape[0],NoModels))
modelnames = ['OLS','LASSO','Ridge','GP-NARX','ES']
omodelnames = ['Observations','OLS','LASSO','Ridge','GP-NARX','ES']







# Fit a linear model using ordinary least squares (OLS)
OLSmdl = np.linalg.lstsq(Z, y, rcond=None)
Yp[:,0] = Z @ OLSmdl[0] 

# Fit a LASSO model
LASSOmdl = linear_model.Lasso(alpha=0.0001,fit_intercept=False)
LASSOmdl.fit(Z, y)
Yp[:,1] = Z @ LASSOmdl.coef_

# Fit a LASSO model
ridgemdl = linear_model.Ridge(alpha=0.1,fit_intercept=False)
ridgemdl.fit(Z, y)
Yp[:,2] = Z @ ridgemdl.coef_




# Fit a GPR model to data
#kernel =  RBF(7) + WhiteKernel(0.01) 
#gpr = GaussianProcessRegressor(kernel=kernel).fit(Z, y)
#Yp[:,3] = gpr.predict(Z)




# <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <>

# Fit a GPyTorch model to data
# Torchify my data
yt = torch.Tensor(y)
Zt = torch.Tensor(Z)
Zt2 = torch.Tensor(Z2)



# We will use the simplest form of GP model, exact inference
class ExactGPModel(gpytorch.models.ExactGP):
    def __init__(self, train_x, train_y, likelihood):
        super(ExactGPModel, self).__init__(train_x, train_y, likelihood)
        self.mean_module = gpytorch.means.LinearMean(train_x.size(1))
        #self.mean_module = gpytorch.means.ConstantMean()
        self.covar_module = gpytorch.kernels.ScaleKernel(gpytorch.kernels.RBFKernel())

    def forward(self, x):
        mean_x = self.mean_module(x)
        covar_x = self.covar_module(x)
        return gpytorch.distributions.MultivariateNormal(mean_x, covar_x)

# initialize likelihood and model
likelihood = gpytorch.likelihoods.GaussianLikelihood()
torchmodel = ExactGPModel(Zt, yt, likelihood)

# Find optimal model hyperparameters
torchmodel.train()
likelihood.train()


# Use the adam optimizer
optimizer = torch.optim.Adam(torchmodel.parameters(), lr=0.1)  # Includes GaussianLikelihood parameters

# "Loss" for GPs - the marginal log likelihood
mll = gpytorch.mlls.ExactMarginalLogLikelihood(likelihood, torchmodel)

training_iter = 75
for i in range(training_iter):
    # Zero gradients from previous iteration
    optimizer.zero_grad()
    # Output from model
    output = torchmodel(Zt)
    # Calc loss and backprop gradients
    loss = -mll(output, yt)
    loss.backward()
    print('Iter %d/%d - Loss: %.3f   lengthscale: %.3f   noise: %.3f' % (
        i + 1, training_iter, loss.item(),
        torchmodel.covar_module.base_kernel.lengthscale.item(),
        torchmodel.likelihood.noise.item()
    ))
    optimizer.step()
    
    
# Get into evaluation (predictive posterior) mode
torchmodel.eval()
likelihood.eval()

Yp[:,3] = torchmodel(Zt).mean.detach()

# <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <>


# Simple Exponential Smoothing
ESmodel = SimpleExpSmoothing(y)
Yp[:,4] = ESmodel.fit(smoothing_level=0.5).fittedvalues





# Plot model fit
t = np.transpose(np.arange(0,y.shape[0]))
plt.figure(figsize=(16, 3))
plt.plot(t,y,'k-')
plt.plot(t,Yp)
plt.legend(omodelnames, loc='lower right')
plt.title('NARX Models in-sample')
plt.grid(True)
plt.show()


# Compute errors
Ype = 0*Yp
for k in range(0,Yp.shape[1]):
    Ype[:,k] = np.cumsum(np.abs(Yp[:,k]-y))    

# Plot Errors
plt.figure(figsize=(16, 3))
ax = plt.axes()
plt.plot(t,Ype)
plt.legend(modelnames, loc='lower right')
plt.title('In-sample Cumulative Error')
plt.grid(True)
plt.show()




# <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <> <>



# Initialize matrix of predictions
Yp = np.empty((y2.shape[0],NoModels))

# Make out of sample predictions
Yp[:,0] = Z2 @ OLSmdl[0]      # OLS   ARX
Yp[:,1] = Z2 @ LASSOmdl.coef_ # LASSO ARX
Yp[:,2] = Z2 @ ridgemdl.coef_ # Ridge ARX
#Yp[:,3] = gpr.predict(Z2)     # GP    NARX
Yp[:,3] = torchmodel(Zt2).mean.detach()    # GP    NARX
Yp[:,4] = Yp[:,1]    # GP    NARX



# Plot Predictions
t2 = np.transpose(np.arange(0,y2.shape[0]))
plt.figure(figsize=(16, 3))
plt.plot(t2,y2,'k-')
plt.plot(t2,Yp)
plt.legend(omodelnames, loc='lower right')
plt.title('ARX Models out-of-sample')
plt.grid(True)
plt.show()


# Compute errors
Ype = 0*Yp
for k in range(0,Yp.shape[1]):
    Ype[:,k] = np.cumsum(np.abs(Yp[:,k]-y2))    

# Plot Errors
plt.figure(figsize=(16, 3))
ax = plt.axes()
plt.plot(t2,Ype)
plt.legend(modelnames, loc='lower right')
plt.title('Out-of-sample Cumulative Error')
plt.grid(True)
plt.show()

