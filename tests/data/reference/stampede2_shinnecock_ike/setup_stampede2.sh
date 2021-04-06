DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# prepare single coldstart directory
pushd ${DIRECTORY}/coldstart >/dev/null 2>&1
sh ../setup.sh.coldstart
ln -sf ../job_adcprep_stampede2.job adcprep.job
ln -sf ../job_adcirc_stampede2.job.coldstart adcirc.job
popd >/dev/null 2>&1

# prepare every hotstart directory
for hotstart in ${DIRECTORY}/runs/*/; do
    pushd ${hotstart} >/dev/null 2>&1
    sh ../../setup.sh.hotstart
    ln -sf ../../job_adcprep_stampede2.job adcprep.job
    ln -sf ../../job_adcirc_stampede2.job.hotstart adcirc.job
    popd >/dev/null 2>&1
done
