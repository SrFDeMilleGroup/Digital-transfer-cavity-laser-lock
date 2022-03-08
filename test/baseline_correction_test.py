from scipy import sparse
from scipy.sparse import linalg
import numpy as np
from scipy.interpolate import CubicSpline
import matplotlib.pyplot as plt
import time

# code from https://stackoverflow.com/a/67509948
def baseline_arPLS(y, ratio=1e-6, lam=100, niter=50, full_output=False):
    # lam for lambda, smoothness parameter
    L = len(y)

    diag = np.ones(L - 2)
    D = sparse.spdiags([diag, -2*diag, diag], [0, -1, -2], L, L - 2)

    H = lam * D.dot(D.T)  # The transposes are flipped w.r.t the Algorithm on pg. 252

    w = np.ones(L)
    W = sparse.spdiags(w, 0, L, L)

    crit = 1
    count = 0

    while crit > ratio:
        z = linalg.spsolve(W + H, W * y)
        d = y - z
        dn = d[d < 0]

        m = np.mean(dn)
        s = np.std(dn)

        w_new = 1 / (1 + np.exp(2 * (d - (2*s - m))/s))

        crit = np.linalg.norm(w_new - w) / np.linalg.norm(w)

        w = w_new
        W.setdiag(w)  # Do not create a new matrix, just update diagonal values

        count += 1

        if count > niter:
            print('Maximum number of iterations exceeded')
            break

    if full_output:
        info = {'num_iter': count, 'stop_criterion': crit}
        return z, d, info
    else:
        return z

def spectra_model(x):
    coeff = np.array([0.1, .2, .1])
    mean = np.array([300, 750, 800])

    stdv = np.array([15, 30, 15])

    terms = []
    for ind in range(len(coeff)):
        term = coeff[ind] * np.exp(-((x - mean[ind]) / stdv[ind])**2)
        terms.append(term)

    spectra = sum(terms)

    return spectra

x_vals = np.arange(1, 1001)
spectra_sim = spectra_model(x_vals)

x_poly = np.array([0, 250, 700, 1000])
y_poly = np.array([2, 1.8, 2.3, 2])

poly = CubicSpline(x_poly, y_poly)
baseline = poly(x_vals)
baseline = np.ones(len(x_vals))

noise = np.random.randn(len(x_vals)) * 0.01
spectra_base = spectra_sim + baseline + noise
t0 = time.time()
repeat = 50
for i in range(repeat):
    _, spectra_arPLS, info = baseline_arPLS(spectra_base, ratio=1e-2, lam=1e5, niter=100,
                                         full_output=True)
print(f"average execution time {(time.time()-t0)/repeat*1000} ms.")

plt.plot(spectra_sim, label="sim")
plt.plot(spectra_base, label="base")
plt.plot(spectra_arPLS, label="arPLS")
plt.legend()
plt.show()