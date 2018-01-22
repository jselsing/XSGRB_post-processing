# -*- coding: utf-8 -*-
# Adding ppxf path
import sys
sys.path.append('/Users/jselsing/Work/Pythonlibs/ppxf/')
import ppxf
import ppxf_util as util
from scipy.special import wofz, erf
from scipy.optimize import curve_fit
import seaborn; seaborn.set_style('ticks')
import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import splrep,splev
from time import clock
from scipy import interpolate


def voigt_base(x, amp=1, cen=0, sigma=1, gamma=0):
    """1 dimensional voigt function.
    see http://en.wikipedia.org/wiki/Voigt_profile
    """
    z = (x-cen + 1j*gamma)/ (sigma*np.sqrt(2.0))
    return amp * wofz(z).real / (sigma*np.sqrt(2*np.pi))


def multi_voigt(x, *params):
    # Multiple voigt-profiles for telluric resolution estimate
    sigma = params[0]
    gamma = params[1]
    c = params[2]
    a = params[3]

    multivoigt = 0
    for ii in range(4, int(4 + len(params[4:])/2)):

        multivoigt += voigt_base(x, params[ii], params[int(len(params[4:])/2 + ii)], sigma, gamma)
    return multivoigt + c + a * x

def find_best_template(wl_obs, flux, err, hdr, spectral_library):

    t2 = clock()

    # Read a spectrum and define the wavelength range
    obs_spectrum = flux
    obs_spectrum_header = hdr
    obs_error_spectrum = abs(err)

    obs_lambda_range = np.array([min(wl), max(wl)])
    z = 0.0 # Initial estimate of the galaxy redshift
    obs_lambda_range = obs_lambda_range/(1+z) # Compute approximate restframe wavelength range

    #Get median of positive values
    m = np.median(obs_error_spectrum[obs_error_spectrum > 0])
    # Assign the median to the negative elements
    obs_error_spectrum[obs_error_spectrum <= 0] = m

    #logarithmically rebin while conserving flux
    tell_obs, obs_lambda, velscale = util.log_rebin(obs_lambda_range, obs_spectrum)
    tell_obs_err, obs_lambda, velscale = util.log_rebin(obs_lambda_range, obs_error_spectrum)


    # Normalize to avoid numerical issues
    norm = tell_obs[int(len(tell_obs)/2)]
    tell_obs = tell_obs/norm
    tell_obs_err = tell_obs_err/norm

    # Load and prepare Model stellar library
    # Extract the wavelength range and logarithmically rebin one spectrum
    # to the same velocity scale of the target spectrum, to determine
    # the size needed for the array which will contain the template spectra.

    hdu = fits.open(spectral_library[0])
    library_spectrum = hdu[0].data
    library_spectrum_header = hdu[0].header
    try:
        wl_lib = np.e**(np.arange((library_spectrum_header['NAXIS1']))*library_spectrum_header['CDELT1']+library_spectrum_header['CRVAL1'])
    except:
        wl_lib = fits.open("/Users/jselsing/Work/spectral_libraries/phoenix_spectral_library/WAVE_PHOENIX-ACES-AGSS-COND-2011.fits")[0].data

    #Make empty template holder
    f = splrep(wl_lib,library_spectrum, k=1)
    hdu_wave_short = splev(wl_obs,f)
    lib_lambda_range = np.array([min(wl_obs),max(wl_obs)])
    tell_lib, lib_lambda, velscale = util.log_rebin(lib_lambda_range, hdu_wave_short, velscale=velscale)
    templates = np.empty((tell_lib.size,len(spectral_library)))

    # Convolve the whole library of spectral templates
    # with the quadratic difference between the target and the
    # library instrumental resolution. Logarithmically rebin
    # and store each template as a column in the array TEMPLATES.

    for j in range(len(spectral_library)):
        t = clock()
        hdu = fits.open(spectral_library[j])
        library_spectrum = hdu[0].data

        # Interpolate template spectrum to match input spectrum
        f = splrep(wl_lib,library_spectrum,k=1)
        interpolated_library_spectrum = splev(wl_obs,f)

        # Logarithmically rebin template spectra
        tell_lib, lib_lambda, velscale = util.log_rebin(lib_lambda_range,interpolated_library_spectrum, velscale=velscale)
        norm = tell_lib[int(len(tell_obs)/2)]
        tell_lib = tell_lib/norm

        templates[:,j] = tell_lib/np.median(tell_lib) # Normalizes templates
        if j % 60 == 0:
            print('Approximated remaining time (s) for setup of template spectra: '+ str(len(spectral_library)*(clock() - t) -  j*(clock() - t)) + 's')

    #Excluding areas of strong telluric absorbtion from fitting
    if obs_spectrum_header['HIERARCH ESO SEQ ARM'] == "UVB":
        mask = (obs_lambda < np.log(5500)) & (obs_lambda > np.log(3100))
        goodPixels = np.where(mask == True)[0]
    elif obs_spectrum_header['HIERARCH ESO SEQ ARM'] == "VIS":
        # mask = (obs_lambda > np.log(5500)) & (obs_lambda < np.log(6350)) | (obs_lambda > np.log(6380)) & (obs_lambda < np.log(6860)) | (obs_lambda > np.log(7045)) & (obs_lambda < np.log(7140)) | (obs_lambda > np.log(7355)) & (obs_lambda < np.log(7570)) | (obs_lambda > np.log(7710)) & (obs_lambda < np.log(8090)) | (obs_lambda > np.log(8400)) & (obs_lambda < np.log(8900)) | (obs_lambda > np.log(9900)) & (obs_lambda < np.log(10100))
        mask = (obs_lambda > np.log(5550)) & (obs_lambda < np.log(5950)) | (obs_lambda > np.log(6400)) & (obs_lambda < np.log(6800)) | (obs_lambda > np.log(7355)) & (obs_lambda < np.log(7570)) | (obs_lambda > np.log(8400)) & (obs_lambda < np.log(8900)) | (obs_lambda > np.log(9900)) & (obs_lambda < np.log(10100))
        goodPixels = np.where(mask == True)[0]
    elif obs_spectrum_header['HIERARCH ESO SEQ ARM'] == "NIR":
        mask = (obs_lambda > np.log(10000)) & (obs_lambda < np.log(10950)) | (obs_lambda > np.log(12240)) & (obs_lambda < np.log(12500)) | (obs_lambda > np.log(12800)) & (obs_lambda < np.log(12950)) | (obs_lambda > np.log(15300)) & (obs_lambda < np.log(17100)) | (obs_lambda > np.log(21500)) & (obs_lambda < np.log(22000)) & (tell_obs > 0)
        goodPixels = np.where(mask == True)[0]

    # Initial parameters for LOSVD
    c = 299792.458
    dv = 15#(logLam2[0]-logLam1[0])*c # km/s
    vel = -100 # Initial estimate of the LOSVD km/s
    start = [vel, dv] # (km/s), starting guess for [V,sigma]

    # Here the actual fit starts.
    print("Fitting ...")
    pp = ppxf.ppxf(templates, tell_obs, tell_obs_err, velscale, start,
                       goodpixels=goodPixels, plot=False, moments=4,
                       degree=3, mdegree=1)
    # pl.show()
    print("Formal errors:")
    print("     dV    dsigma   dh3      dh4")
    print("".join("%8.2g" % f for f in pp.error*np.sqrt(pp.chi2)))

    print('elapsed time (s) for ppxf: ', clock() - t2)



    print('Best-fitting R:', c / pp.sol[1])
    print('Best-fitting error on R:', (c / pp.sol[1] - c / (pp.sol[1] + pp.error[1]*np.sqrt(pp.chi2))))

    print(np.array(spectral_library)[np.ceil(pp.weights).astype("bool")])
    # print(spectral_library[(np.array(pp.weights).astype("int")).astype("bool")])

    print('Rebinning to linear axes')
    f = interp1d(np.e**obs_lambda, pp.galaxy, bounds_error=False, fill_value=np.nan)
    obj_spec = f(wl_obs)
    f = interp1d(np.e**obs_lambda, pp.bestfit, bounds_error=False, fill_value=np.nan)
    template_fit = f(wl_obs)

    return obj_spec, template_fit, obs_spectrum_header
#------------------------------------------------------------------------------

if __name__ == '__main__':
    from astropy.io import fits
    import glob
    import matplotlib.pyplot as pl
    import numpy as np
    from scipy.interpolate import splrep, splev, interp1d

    #Files
    root_dir = "/Users/jselsing/Work/work_rawDATA/STARGATE/GRB171010A/"
    # root_dir = "/Users/jselsing/Work/work_rawDATA/SN2005ip/"
    # root_dir = "/Users/jselsing/Work/work_rawDATA/SN2013l/"
    OB = "OB1"
    xsgrbobject = glob.glob(root_dir+'reduced_data/'+OB+'_telluric/*/*/*.fits')
    tell_file = [kk for kk in xsgrbobject if "TELL_SLIT_FLUX_MERGE1D" in kk]
    tell_file_2D = [kk for kk in xsgrbobject if "TELL_SLIT_FLUX_MERGE2D" in kk]
    # tell_file = [kk for kk in xsgrbobject if "TELL_SLIT_MERGE1D" in kk and "NIR" in kk and "OB4" in kk]
    # tell_file_2D = [kk for kk in xsgrbobject if "TELL_SLIT_MERGE2D" in kk and "NIR" in kk and "OB4" in kk]
    # tell_file = ["/Users/jselsing/Work/work_rawDATA/XSGRB/GRB161023A/Extfits/tmp/VISOB1TELL_CORR.fits"]
    # root_dir = "/Users/jselsing/Work/work_rawDATA/XSGRB/GRB161023A/Extfits/tmp/"
 # and "NIR" in kk
    #Load in Model steller spetra
    library = glob.glob('/Users/jselsing/Work/spectral_libraries/phoenix_spectral_library/*/*.fits')
    # library = glob.glob('/Users/jselsing/Work/spectral_libraries/phoenix_spectral_library/TEMP/PHOENIX-ACES-AGSS-COND-2011_R10000FITS_Z-0.0/*.fits')


    for kk, ii in enumerate(tell_file):

        print('Working on object: '+ii)
        tell_file = fits.open(ii)
        namesplit = ii.split("/")

        # OB = OB"OB12" # namesplit[-4][:3]

        # exit()
        arm = tell_file[0].header["HIERARCH ESO SEQ ARM"]
        filenam = "".join(("".join(namesplit[-2].split(":")).split(".")))
        file_name = arm + OB + "TELL"+str(kk + 1) #+ filenam



        wl = 10.*((np.arange(tell_file[0].header['NAXIS1']) - tell_file[0].header['CRPIX1'])*tell_file[0].header['CDELT1']+tell_file[0].header['CRVAL1'])
        # IDP files
        # wl = 10*tell_file[1].data.field("WAVE").flatten()



        # response_path = None
        # for ll in glob.glob("/".join(root_dir.split("/")[:-1])+"/data_with_raw_calibs/M*.fits"):
        #     print(ll)
        #     try:
        #         filetype = fits.open(ll)[0].header["CDBFILE"]
        #         print(filetype)
        #         if "GRSF" in filetype and arm in filetype:
        #             response_path = ll
        #     except:
        #         pass
        # if response_path:
        #     print("Found master response at: "+str(response_path))
        # elif not response_path:
        #     print("None found. Skipping flux calibration.")
        # # Apply flux calibration from master response file
        # resp = fits.open(response_path)
        # wl_response, response = resp[1].data.field('LAMBDA'), resp[1].data.field('RESPONSE')

        # f = interpolate.interp1d(10 * wl_response, response, bounds_error=False)
        # response = f(wl)

        # if arm == "UVB" or arm == "VIS":
        #     gain = tell_file[0].header["HIERARCH ESO DET OUT1 GAIN"]
        # elif arm == "NIR":
        #     gain = 1.0/2.12
        # else:
        #     print("Missing arm keyword in header. Stopping.")
        #     exit()

        # # Apply atmospheric extinciton correction
        # atmpath = "data/esostatic/xsh_paranal_extinct_model_"+arm.lower()+".fits"
        # ext_atm = fits.open(atmpath)
        # wl_ext_atm, ext_atm = ext_atm[1].data.field('LAMBDA'), ext_atm[1].data.field('EXTINCTION')

        # f = interpolate.interp1d(10. * wl_ext_atm, ext_atm, bounds_error=False)
        # ext_atm = f(wl)
        # response = (10. * tell_file[0].header['CDELT1'] * response * (10.**(0.4*tell_file[0].header['HIERARCH ESO TEL AIRM START'] * ext_atm))) / ( gain * tell_file[0].header['EXPTIME'])


        flux = tell_file[0].data#*response
        err = tell_file[1].data#*response
        # bpmap = tell_file[2].data
        bpmap = np.zeros_like(tell_file[2].data)

        # flux = tell_file[1].data.field("FLUX").flatten()
        # err = tell_file[1].data.field("ERR").flatten()
        # bpmap = tell_file[1].data.field("QUAL").flatten()

        wl_temp = wl[~(bpmap.astype("bool"))][200:-100]
        flux_temp = flux[~(bpmap.astype("bool"))][200:-100]
        err_temp = err[~(bpmap.astype("bool"))][200:-100]
        f = interpolate.interp1d(wl_temp, flux_temp, kind="nearest", fill_value="extrapolate")
        flux = f(wl)
        f = interpolate.interp1d(wl_temp, err_temp, kind="nearest", fill_value="extrapolate")
        err = f(wl)

        if arm == "UVB":

            mask2 = (wl > wl[int(len(wl)/2)] - 500) & (wl < wl[int(len(wl)/2)] + 500)

        elif arm == "VIS":
            mask = (wl > 6881) & (wl < 6921)
            mask2 = (wl > wl[int(len(wl)/2)] - 500) & (wl < wl[int(len(wl)/2)] + 500)
            amps = 19 * [-1e-12]
            cens = [6.88392564e+03, 6.88585686e+03, 6.88683982e+03, 6.88904597e+03, 6.89000132e+03, 6.89247384e+03, 6.89341075e+03, 6.89613979e+03, 6.89706733e+03, 6.90005809e+03, 6.90097910e+03, 6.90422797e+03, 6.90513024e+03, 6.90863564e+03, 6.90954103e+03, 6.91332001e+03, 6.91421144e+03, 6.91822776e+03, 6.91913232e+03]
        elif arm == "NIR":
            mask = (wl > 17475) & (wl < 17730)
            mask2 = (wl > wl[int(len(wl)/2)] - 500) & (wl < wl[int(len(wl)/2)]+ 500)
            amps = 12 * [-1e-13]
            cens = [17510, 17546, 17550, 17563, 17569, 17604, 17620, 17625, 17654, 17676, 17691, 17702]


        tell_file2D = fits.open(tell_file_2D[kk])
        min_idx, max_idx = min(*np.where(mask2)), max(*np.where(mask2))
        v_len = np.shape(tell_file2D[0].data)[0]

        profile = np.median(tell_file2D[0].data[int(v_len/3):int(-v_len/3), min_idx:max_idx], axis= 1)

        xarr = np.arange(len(profile))
        # pl.plot(xarr, profile)
        # pl.show()
        p0 = [max(profile), len(xarr)/2, 5, 0]
        popt, pcuv = curve_fit(voigt_base, xarr, profile, p0=p0)
        # pl.plot(xarr, voigt_base(xarr, *popt))
        # pl.ylim(0, 5e-14)
        # pl.show()
        fwhm_g, fwhm_l = 2.35 * popt[2], 2*popt[3]
        fwhm_g_var, fwhm_l_var = 2.35 * pcuv[2, 2], 2*pcuv[3, 3]
        fwhm = 0.5346 * fwhm_l + np.sqrt(0.2166 * fwhm_l**2 + fwhm_g**2)
        dfdl = 0.5346 - 0.5 * ((0.2166 * fwhm_l**2 + fwhm_g**2) ** (-3/2)) *(2 * 0.2166 * fwhm_l)
        dfdg = - 0.5 * ((0.2166 * fwhm_l**2 + fwhm_g**2) ** (-3/2)) *(2 * fwhm_g)
        fwhm_err = np.sqrt((dfdl**2) * (fwhm_g_var) + (dfdg**2) * (fwhm_l_var))
        seeing_fwhm = fwhm*tell_file2D[0].header["CD2_2"]
        print(file_name, seeing_fwhm)
        seeing_fwhm_err = fwhm_err*tell_file2D[0].header["CD2_2"]
        p0 =  [0.2, 0, max(flux[mask]), 0] + amps + cens

        try:
            popt, pcuv = curve_fit(multi_voigt, wl[mask], flux[mask], p0=p0)
        except:
            continue
        midwl = np.median(wl[mask])
        R = midwl / (popt[0]*2.35)
        Rerr =   R - midwl /((popt[0] + np.sqrt(np.diag(pcuv)[0]))*2.35)
        x = np.arange(min(wl[mask]), max(wl[mask]), 0.01)
        pl.plot(x, multi_voigt(x, *popt), label="R = "+str(int(np.around(R, decimals = -2))) + " +- " + str(int(np.around(Rerr, decimals = -2))))
        pl.plot(wl[mask], flux[mask], label="Seeing FWHM = "+str(np.around(seeing_fwhm, decimals = 2)) + " +- " + str(np.around(seeing_fwhm_err, decimals = 2)))
        pl.xlabel(r"Wavelength / [$\mathrm{\AA}$]")
        pl.ylabel(r'Flux density [erg s$^{-1}$ cm$^{-1}$ $\AA^{-1}$]')
        pl.ylim((min(flux[mask]), max(flux[mask])*1.10))
        pl.legend()

        pl.savefig(root_dir+file_name+"_resolution.pdf")
        pl.clf()
        # pl.show()
        continue
        gal, fit, hdr = find_best_template(wl, flux, err, tell_file[0].header, library)
        fit[np.isinf(fit)] = gal[np.isinf(fit)]

        pl.errorbar(wl[::5], flux[::5], yerr=err[::5], fmt=".k", capsize=0, elinewidth=0.5, ms=3, alpha=0.7)
        pl.plot(wl[::5], gal[::5], linestyle="steps-mid", lw=0.5)
        pl.plot(wl[::5], fit[::5], linestyle="steps-mid", lw=0.5)
        pl.plot(wl[::5], gal[::5] - fit[::5], linestyle="steps-mid", lw=1.0, alpha=0.5, color = "grey")
        pl.axhline(0, linestyle="dashed", color = "black", lw = 0.4)
        pl.xlabel(r"Wavelength / [$\mathrm{\AA}$]")
        pl.ylabel(r'Flux density [erg s$^{-1}$ cm$^{-1}$ $\AA^{-1}$]')
        pl.ylim(min(gal[::5] - fit[::5]), max(fit))
        pl.xlim(min(wl), max(wl))

        pl.savefig(root_dir+file_name+"_fit.pdf", rasterize=True)
        # pl.show()
        pl.close()



        dt = [("wl", np.float64), ("telluric_star", np.float64), ("Optimal_template_fit", np.float64)]
        data = np.array(zip(wl, gal, fit), dtype=dt)
        np.savetxt(root_dir+file_name+".dat", data, header="wl telluric_star Optimal_template_fit")

        # print("close the plot to continue")
        # pl.show(block=True)
