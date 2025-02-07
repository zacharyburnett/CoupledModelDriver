from copy import copy
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path
from typing import Any, Dict, List

from nemspy import ModelingSystem
from nemspy.model.base import ModelEntry
from pyschism.driver import ModelDriver
from pyschism.mesh import Hgrid

from coupledmodeldriver.configure import NEMSJSON
from coupledmodeldriver.configure.base import (
    ConfigurationJSON,
    ModelDriverJSON,
    NEMSCapJSON,
    SlurmJSON,
)
from coupledmodeldriver.configure.configure import RunConfiguration
from coupledmodeldriver.configure.forcings.base import (
    ForcingJSON,
    TidalForcingJSON,
    BestTrackForcingJSON,
    NationalWaterModelFocringJSON,
)
from coupledmodeldriver.generate.schism.base import SCHISMJSON
from coupledmodeldriver.platforms import Platform
from coupledmodeldriver.utilities import LOGGER


class SCHISMRunConfiguration(RunConfiguration):
    """
    run configuration for SCHISM-only run, with optional tidal and / or best track forcing using SCHISM's input capability
    """

    REQUIRED = {
        ModelDriverJSON,
        SlurmJSON,
        SCHISMJSON,
    }
    SUPPLEMENTARY = {
        TidalForcingJSON,
        BestTrackForcingJSON,
        NationalWaterModelFocringJSON,
    }

    def __init__(
        self,
        mesh_directory: PathLike,
        modeled_start_time: datetime,
        modeled_end_time: datetime,
        modeled_timestep: timedelta,
        tidal_spinup_duration: timedelta = None,
        platform: Platform = None,
        perturbations: Dict[str, Dict[str, Any]] = None,
        forcings: List[ForcingJSON] = None,
        schism_processors: int = None,
        slurm_job_duration: timedelta = None,
        slurm_partition: str = None,
        slurm_email_address: str = None,
        schism_executable: PathLike = None,
        schism_hotstart_combiner: PathLike = None,
        schism_schout_combiner: PathLike = None,
        schism_use_old_io: bool = False,
        source_filename: PathLike = None,
    ):
        """
        :param mesh_directory: path to input mesh directory (containing ``fort.13``, ``fort.14``)
        :param modeled_start_time: start time within the modeled system
        :param modeled_end_time: end time within the modeled system
        :param modeled_timestep: time interval within the modeled system
        :param tidal_spinup_duration: spinup time for SCHISM tidal coldstart
        :param platform: HPC platform for which to configure
        :param perturbations: dictionary of runs encompassing run names to parameter values
        :param forcings: list of forcing configurations to connect to SCHISM
        :param schism_processors: numbers of processors to assign for SCHISM
        :param slurm_job_duration: wall clock time of job
        :param slurm_partition: Slurm partition
        :param slurm_email_address: email address to send Slurm notifications
        :param schism_executable: filename of compiled ``pschism-TVD_VL``
        :param schism_hotstart_combiner: filename of compiled hotstart combiner
        :param schism_schout_combiner: filename of compiled SCHISM old output combiner
        :param schism_use_old_io: flag to indicate if the compiled SCHISM uses old IO
        :param source_filename: path to module file to ``source``
        """

        self.__pyschism_mesh = None

        if not isinstance(mesh_directory, Path):
            mesh_directory = Path(mesh_directory)

        if platform is None:
            platform = Platform.LOCAL

        if forcings is None:
            forcings = []

        if schism_processors is None:
            schism_processors = 11

        if schism_executable is None:
            schism_executable = 'pschism-TVD_VL'

        if schism_hotstart_combiner is None:
            schism_hotstart_combiner = 'combine_hotstart7'

        if schism_schout_combiner is None:
            schism_schout_combiner = 'combine_output11'

        slurm = SlurmJSON(
            account=platform.value['slurm_account'],
            tasks=schism_processors,
            partition=slurm_partition,
            job_duration=slurm_job_duration,
            email_address=slurm_email_address,
        )

        schism = SCHISMJSON(
            schism_executable_path=schism_executable,
            schism_hotstart_combiner_path=schism_hotstart_combiner,
            schism_schout_combiner_path=schism_schout_combiner,
            schism_use_old_io=schism_use_old_io,
            modeled_start_time=modeled_start_time,
            modeled_end_time=modeled_end_time,
            modeled_timestep=modeled_timestep,
            fgrid_path=mesh_directory / 'manning.gr3',
            hgrid_path=mesh_directory / 'hgrid.gr3',
            tidal_spinup_duration=tidal_spinup_duration,
            source_filename=source_filename,
            slurm_configuration=slurm,
            processors=schism_processors,
        )

        driver = ModelDriverJSON(platform=platform, perturbations=perturbations)
        super().__init__([driver, slurm, schism])

        for forcing in forcings:
            self.add_forcing(forcing)

    def add_forcing(self, forcing: ForcingJSON):
        if forcing not in self:
            forcing = self[self.add(forcing)]
            try:
                self['schism'].add_forcing(forcing)
            except Exception as error:
                LOGGER.error(error)

    @property
    def forcings(self) -> List[ForcingJSON]:
        return [
            configuration
            for configuration in self.configurations
            if isinstance(configuration, ForcingJSON)
        ]

    @property
    def pyschism_mesh(self) -> Hgrid:
        return self['schism'].pyschism_mesh

    @pyschism_mesh.setter
    def pyschism_mesh(self, pyschism_mesh: Hgrid):
        self['schism'].pyschism_mesh = pyschism_mesh

    @property
    def pyschism_driver(self) -> ModelDriver:
        return self['schism'].pyschism_driver

    def files_exist(self, directory: PathLike) -> bool:
        if not isinstance(directory, Path):
            directory = Path(directory)

        if not directory.exists():
            return False

        files_to_write = [
            'bctides.in',
            'hgrid.gr3',
            'hgrid.ll',
            'manning.gr3',
            'outputs',
            'param.nml',
            'vgrid.in',
            'schism.job',
        ]
        if 'nems' in self:
            files_to_write.extend(
                ['nems.configure', 'atm_namelist.rc', 'model_configure', 'config.rc',]
            )
        existing_files = [filename.name for filename in directory.iterdir()]

        return all([filename in existing_files for filename in files_to_write])

    def __copy__(self) -> 'SCHISMRunConfiguration':
        return self.__class__.from_configurations(
            [copy(configuration) for configuration in self.configurations]
        )

    @classmethod
    def from_configurations(
        cls, configurations: List[ConfigurationJSON]
    ) -> 'SCHISMRunConfiguration':
        required = {configuration_class: None for configuration_class in cls.REQUIRED}
        supplementary = {
            configuration_class: None for configuration_class in cls.SUPPLEMENTARY
        }

        for configuration in configurations:
            for configuration_class in required:
                if isinstance(configuration, configuration_class):
                    if required[configuration_class] is None:
                        required[configuration_class] = configuration
                        break
                    else:
                        raise ValueError(
                            f'multiple configurations given for "{configuration_class.__name__}"'
                        )
            for configuration_class in supplementary:
                if isinstance(configuration, configuration_class):
                    supplementary[configuration_class] = configuration

        instance = RunConfiguration(required.values())
        instance.__class__ = cls

        instance['modeldriver'] = required[ModelDriverJSON]
        instance['slurm'] = required[SlurmJSON]
        instance['schism'] = required[SCHISMJSON]

        forcings = [
            configuration
            for configuration in supplementary.values()
            if isinstance(configuration, ForcingJSON)
        ]
        for forcing in forcings:
            instance.add_forcing(forcing)

        return instance

    @classmethod
    def read_directory(
        cls, directory: PathLike, required: List[type] = None, supplementary: List[type] = None
    ) -> 'SCHISMRunConfiguration':
        if not isinstance(directory, Path):
            directory = Path(directory)
        if directory.is_file():
            directory = directory.parent
        if required is None:
            required = set()
        required.update(SCHISMRunConfiguration.REQUIRED)
        if supplementary is None:
            supplementary = set()
        supplementary.update(SCHISMRunConfiguration.SUPPLEMENTARY)

        return super().read_directory(directory, required, supplementary)


# class NEMSSCHISMRunConfiguration(SCHISMRunConfiguration):
#     """
#     run configuration coupling SCHISM with other models / forcings using NUOPC NEMS
#     """
#
#     REQUIRED = {
#         ModelDriverJSON,
#         NEMSJSON,
#         SlurmJSON,
#         SCHISMJSON,
#     }
#
#     def __init__(
#         self,
#         mesh_directory: PathLike,
#         modeled_start_time: datetime,
#         modeled_end_time: datetime,
#         modeled_timestep: timedelta,
#         nems_interval: timedelta,
#         nems_connections: List[str],
#         nems_mediations: List[str],
#         nems_sequence: List[str],
#         tidal_spinup_duration: timedelta = None,
#         platform: Platform = None,
#         perturbations: Dict[str, Dict[str, Any]] = None,
#         forcings: List[ForcingJSON] = None,
#         schism_processors: int = None,
#         slurm_job_duration: timedelta = None,
#         slurm_partition: str = None,
#         slurm_email_address: str = None,
#         nems_executable: PathLike = None,
#         schism_hotstart_combiner: PathLike = None,
#         schism_schout_combiner: PathLike = None,
#         # schism_use_old_io: bool = False,
#         adcprep_executable: PathLike = None,
#         aswip_executable: PathLike = None,
#         source_filename: PathLike = None,
#     ):
#         """
#         :param mesh_directory: path to input mesh directory (containing ``fort.13``, ``fort.14``)
#         :param modeled_start_time: start time within the modeled system
#         :param modeled_end_time: end time within the modeled system
#         :param modeled_timestep: time interval within the modeled system
#         :param nems_interval: modeled time interval of main NEMS loop
#         :param nems_connections: list of NEMS connections as strings (i.e. ``ATM -> OCN``)
#         :param nems_mediations: list of NEMS mediations, including functions
#         :param nems_sequence: list of NEMS entries in sequence order
#         :param schism_processors: numbers of processors to assign for SCHISM
#         :param platform: HPC platform for which to configure
#         :param tidal_spinup_duration: spinup time for SCHISM tidal coldstart
#         :param perturbations: dictionary of runs encompassing run names to parameter values
#         :param forcings: list of forcing configurations to connect to SCHISM
#         :param slurm_job_duration: wall clock time of job
#         :param slurm_partition: Slurm partition
#         :param slurm_email_address: email address to send Slurm notifications
#         :param nems_executable: filename of compiled ``schism``
#         :param source_filename: path to module file to ``source``
#         """
#
#         # TODO: Implement nems coupling for SCHISM
#
#         self.__nems = None
#
#         super().__init__(
#             mesh_directory=mesh_directory,
#             modeled_start_time=modeled_start_time,
#             modeled_end_time=modeled_end_time,
#             modeled_timestep=modeled_timestep,
#             tidal_spinup_duration=tidal_spinup_duration,
#             platform=platform,
#             perturbations=perturbations,
#             forcings=None,
#             schism_processors=schism_processors,
#             slurm_job_duration=slurm_job_duration,
#             slurm_partition=slurm_partition,
#             slurm_email_address=slurm_email_address,
#             schism_executable=nems_executable,
#             source_filename=source_filename,
#         )
#
#         nems = NEMSJSON(
#             executable_path=nems_executable,
#             modeled_start_time=modeled_start_time,
#             modeled_end_time=modeled_end_time,
#             interval=nems_interval,
#             connections=nems_connections,
#             mediations=nems_mediations,
#             sequence=nems_sequence,
#         )
#
#         self[nems.name.lower()] = nems
#
#         for forcing in forcings:
#             self.add_forcing(forcing)
#
#         self['slurm'].tasks = self.nemspy_modeling_system.processors
#
#     @property
#     def nemspy_entries(self) -> List[ModelEntry]:
#         return [
#             configuration.nemspy_entry
#             for configuration in self.configurations
#             if isinstance(configuration, NEMSCapJSON)
#         ]
#
#     @property
#     def nemspy_modeling_system(self) -> ModelingSystem:
#         return self['nems'].to_nemspy(self.nemspy_entries)
#
#     def add_forcing(self, forcing: ForcingJSON):
#         if forcing not in self:
#             forcing = self[self.add(forcing)]
#             self['schism'].add_forcing(forcing)
#
#     @classmethod
#     def from_configurations(
#         cls, configurations: List[ConfigurationJSON]
#     ) -> 'NEMSSCHISMRunConfiguration':
#         instance = SCHISMRunConfiguration.from_configurations(configurations)
#         instance.__class__ = cls
#
#         nems = None
#         for configuration in configurations:
#             if isinstance(configuration, NEMSJSON):
#                 if nems is None:
#                     nems = configuration
#                     break
#                 else:
#                     raise ValueError(
#                         f'multiple configurations given for "{NEMSJSON.__name__}"'
#                     )
#         instance['nems'] = nems
#
#         return instance
#
#     @classmethod
#     def read_directory(
#         cls, directory: PathLike, required: List[type] = None, supplementary: List[type] = None
#     ) -> 'NEMSSCHISMRunConfiguration':
#         if not isinstance(directory, Path):
#             directory = Path(directory)
#         if directory.is_file():
#             directory = directory.parent
#         if required is None:
#             required = set()
#         required.update(NEMSSCHISMRunConfiguration.REQUIRED)
#         if supplementary is None:
#             supplementary = set()
#         supplementary.update(NEMSSCHISMRunConfiguration.SUPPLEMENTARY)
#
#         return super().read_directory(directory, required, supplementary)
