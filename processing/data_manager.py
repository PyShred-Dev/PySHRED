import torch
from .utils import *
from .data_processor import *

class SHREDDataManager:
    """
    SHREDDataManager is the orchestrator of SHREDDataProcessor objects.
    methods:
    - add: for creating SHREDData objects and adding to SHREDDataManager
    - remove: for removing SHREDData objects from SHREDDataManager (to be implemented)
    - preprocess: for generating train, val, and test SHREDDataset objects
    - postprocess
    """

    METHODS = {
        'all': ['reconstructor', 'predictor', 'sensor_forecaster'],
        'reconstruct': ['reconstructor'],
        'predict': ['predictor'],
        'forecast': ['sensor_forecaster', 'predictor']
    }


    def __init__(self, lags = 20, time = None, train_size = 0.8, val_size = 0.1, test_size = 0.1, compression = True, method = 'all'):
        self.compression = compression
        self.time = time # expects a 1D numpy array
        self.lags = lags # number of time steps to look back
        self.data_processors = [] # a list storing SHREDDataProcessor objects
        self.random_indices = None # a dict storing 'train', 'val', 'test' indices for SHRED reconstructor
        self.sequential_indices = None # a dict storing 'train', 'val', 'test' indices for SHRED forecastor
        self.train_size = train_size
        self.val_size = val_size
        self.test_size = test_size
        self.train_dataset = None
        self.val_dataset = None
        self.test_dataset = None
        self.reconstructor = []
        self.sensor_forecaster = []
        self.predictor = []
        self.input_summary = None #
        self.sensor_measurements = None # all sensor measurement
        self.method = method

    def add_field(self, data, random_sensors = None, stationary_sensors = None, mobile_sensors = None, compression = None, id = None, time = None):
        """
        Creates and adds a new SHREDDataProcessor object.
        - file path: file path to data (string)
        - random_sensors: number of randomly placed stationary sensors (integer).
        - stationary_sensors: coordinates of stationary sensors. Each sensor coordinate is a tuple.
                              If multiple stationary sensors, put tuples into a list (tuple or list of tuples).
        - mobile_sensors: list of coordinates (tuple) for a mobile sensor (length of list should match number of timesteps in `data`).
                          If multiple mobile_sensors, use a nested list (list of tuples, or nested list of tuples).
        - time: 1D numpy array of timestamps
        - lags: number of time steps to look back (integer).
        - compression: dimensionality reduction (boolean or integer).
        - id: unique identifier for the dataset (string).
        """
        compression = compression if compression is not None else self.compression
        time = time if time is not None else self.time


        # create and initialize SHREDData object
        data_processor = SHREDDataProcessor(
            data=data,
            random_sensors=random_sensors,
            stationary_sensors=stationary_sensors,
            mobile_sensors=mobile_sensors,
            lags=self.lags,
            time=time,
            compression=compression,
            id=id
        )

        # save sensor-related information to sensor-related attributes
        if data_processor.sensor_summary is not None and data_processor.sensor_measurements_pd is not None:
            if self.input_summary is None and self.sensor_measurements is None:
                self.input_summary = data_processor.sensor_summary
                self.sensor_measurements = data_processor.sensor_measurements_pd
            else:
                self.input_summary = pd.concat([self.input_summary, data_processor.sensor_summary], axis = 0).reset_index(drop=True)
                self.sensor_measurements = pd.merge(self.sensor_measurements, data_processor.sensor_measurements_pd, on='time', how = 'inner')


        # generate train/val/test indices
        if len(self.data_processors) == 0:
            self.random_indices = get_train_val_test_indices(len(time), self.train_size, self.val_size, self.test_size, method = "random")
            self.sequential_indices = get_train_val_test_indices(len(time), self.train_size, self.val_size, self.test_size, method = "sequential")


        if 'reconstructor' in self.METHODS[self.method]:
            dataset_dict = data_processor.generate_dataset(
                self.random_indices['train'],
                self.random_indices['val'],
                self.random_indices['test'],
                method='reconstructor'
            )
            self.reconstructor.append(dataset_dict)

        if 'predictor' in self.METHODS[self.method]:
            dataset_dict = data_processor.generate_dataset(
                self.sequential_indices['train'],
                self.sequential_indices['val'],
                self.sequential_indices['test'],
                method='predictor' # different name so different scalers etc.
            )
            self.predictor.append(dataset_dict)

        if 'sensor_forecaster' in self.METHODS[self.method]:
            dataset_dict = data_processor.generate_dataset(
                self.sequential_indices['train'],
                self.sequential_indices['val'],
                self.sequential_indices['test'],
                method='sensor_forecaster'
            )
            self.sensor_forecaster.append(dataset_dict)

        data_processor.discard_data()
        self.data_processors.append(data_processor)


    def preprocess(self):
        """
        Generates train, val, and test SHREDDataset objects.
        """

        def concatenate_datasets(existing_X, existing_y, new_X, new_y):
            """
            Helper function to concatenate datasets along the last axis, handling None values.
            """
            combined_X = None
            combined_y = None

            if existing_X is None:
                combined_X = new_X
            elif new_X is None:
                combined_X = existing_X
            else:
                combined_X = np.concatenate((existing_X, new_X), axis=-1)
            
            if existing_y is None:
                combined_y = new_y
            elif new_y is None:
                combined_y = existing_y
            else:
                combined_y = np.concatenate((existing_y, new_y), axis=-1)

            return (
                combined_X,
                combined_y,
            )

        # Initialize datasets
        X_train_reconstructor, y_train_reconstructor = None, None
        X_val_reconstructor, y_val_reconstructor = None, None
        X_test_reconstructor, y_test_reconstructor = None, None

        X_train_predictor, y_train_predictor = None, None
        X_val_predictor, y_val_predictor = None, None
        X_test_predictor, y_test_predictor = None, None

        X_train_sensor_forecaster, y_train_sensor_forecaster = None, None
        X_val_sensor_forecaster, y_val_sensor_forecaster = None, None
        X_test_sensor_forecaster, y_test_sensor_forecaster = None, None

        train_reconstructor_dataset = None
        val_reconstructor_dataset = None
        test_reconstructor_dataset = None
        train_predictor_dataset = None
        val_predictor_dataset = None
        test_predictor_dataset = None
        train_sensor_forecaster_dataset = None
        val_sensor_forecaster_dataset = None
        test_sensor_forecaster_dataset = None

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Process random reconstructor datasets
        if 'reconstructor' in self.METHODS[self.method]:
            for dataset_dict in self.reconstructor:
                X_train_reconstructor, y_train_reconstructor = concatenate_datasets(
                    X_train_reconstructor, y_train_reconstructor, dataset_dict['train'][0], dataset_dict['train'][1]
                )
                X_val_reconstructor, y_val_reconstructor = concatenate_datasets(
                    X_val_reconstructor, y_val_reconstructor, dataset_dict['val'][0], dataset_dict['val'][1]
                )
                X_test_reconstructor, y_test_reconstructor = concatenate_datasets(
                    X_test_reconstructor, y_test_reconstructor, dataset_dict['test'][0], dataset_dict['test'][1]
                )
            # Convert data to torch tensors and move to the specified device
            X_train_reconstructor = torch.tensor(X_train_reconstructor, dtype=torch.float32, device=device)
            y_train_reconstructor = torch.tensor(y_train_reconstructor, dtype=torch.float32, device=device)
            X_val_reconstructor = torch.tensor(X_val_reconstructor, dtype=torch.float32, device=device)
            y_val_reconstructor = torch.tensor(y_val_reconstructor, dtype=torch.float32, device=device)
            X_test_reconstructor = torch.tensor(X_test_reconstructor, dtype=torch.float32, device=device)
            y_test_reconstructor = torch.tensor(y_test_reconstructor, dtype=torch.float32, device=device)
            # Create TimeSeriesDataset objects
            train_reconstructor_dataset = TimeSeriesDataset(X_train_reconstructor, y_train_reconstructor)
            val_reconstructor_dataset = TimeSeriesDataset(X_val_reconstructor, y_val_reconstructor)
            test_reconstructor_dataset = TimeSeriesDataset(X_test_reconstructor, y_test_reconstructor)
        
        # Process random reconstructor datasets
        if 'predictor' in self.METHODS[self.method]:
            for dataset_dict in self.predictor:
                X_train_predictor, y_train_predictor = concatenate_datasets(
                    X_train_predictor, y_train_predictor, dataset_dict['train'][0], dataset_dict['train'][1]
                )
                X_val_predictor, y_val_predictor = concatenate_datasets(
                    X_val_predictor, y_val_predictor, dataset_dict['val'][0], dataset_dict['val'][1]
                )
                X_test_predictor, y_test_predictor = concatenate_datasets(
                    X_test_predictor, y_test_predictor, dataset_dict['test'][0], dataset_dict['test'][1]
                )
            X_train_predictor = torch.tensor(X_train_predictor, dtype=torch.float32, device=device)
            y_train_predictor = torch.tensor(y_train_predictor, dtype=torch.float32, device=device)
            X_val_predictor = torch.tensor(X_val_predictor, dtype=torch.float32, device=device)
            y_val_predictor = torch.tensor(y_val_predictor, dtype=torch.float32, device=device)
            X_test_predictor = torch.tensor(X_test_predictor, dtype=torch.float32, device=device)
            y_test_predictor = torch.tensor(y_test_predictor, dtype=torch.float32, device=device)
            train_predictor_dataset = TimeSeriesDataset(X_train_predictor, y_train_predictor)
            val_predictor_dataset = TimeSeriesDataset(X_val_predictor, y_val_predictor)
            test_predictor_dataset = TimeSeriesDataset(X_test_predictor, y_test_predictor)

        # Process forecastor datasets
        if 'sensor_forecaster' in self.METHODS[self.method]:
            for dataset_dict in self.sensor_forecaster:
                X_train_sensor_forecaster, y_train_sensor_forecaster = concatenate_datasets(
                    X_train_sensor_forecaster, y_train_sensor_forecaster, dataset_dict['train'][0], dataset_dict['train'][1]
                )
                X_val_sensor_forecaster, y_val_sensor_forecaster = concatenate_datasets(
                    X_val_sensor_forecaster, y_val_sensor_forecaster, dataset_dict['val'][0], dataset_dict['val'][1]
                )
                X_test_sensor_forecaster, y_test_sensor_forecaster = concatenate_datasets(
                    X_test_sensor_forecaster, y_test_sensor_forecaster, dataset_dict['test'][0], dataset_dict['test'][1]
                )
            X_train_sensor_forecaster = torch.tensor(X_train_sensor_forecaster, dtype=torch.float32, device=device)
            y_train_sensor_forecaster = torch.tensor(y_train_sensor_forecaster, dtype=torch.float32, device=device)
            X_val_sensor_forecaster = torch.tensor(X_val_sensor_forecaster, dtype=torch.float32, device=device)
            y_val_sensor_forecaster = torch.tensor(y_val_sensor_forecaster, dtype=torch.float32, device=device)
            X_test_sensor_forecaster = torch.tensor(X_test_sensor_forecaster, dtype=torch.float32, device=device)
            y_test_sensor_forecaster = torch.tensor(y_test_sensor_forecaster, dtype=torch.float32, device=device)
            train_sensor_forecaster_dataset = TimeSeriesDataset(X_train_sensor_forecaster, y_train_sensor_forecaster)
            val_sensor_forecaster_dataset = TimeSeriesDataset(X_val_sensor_forecaster, y_val_sensor_forecaster)
            test_sensor_forecaster_dataset = TimeSeriesDataset(X_test_sensor_forecaster, y_test_sensor_forecaster)

        SHRED_train_dataset = SHREDDataset(train_reconstructor_dataset, train_predictor_dataset, train_sensor_forecaster_dataset)
        SHRED_val_dataset = SHREDDataset(val_reconstructor_dataset, val_predictor_dataset, val_sensor_forecaster_dataset)
        SHRED_test_dataset = SHREDDataset(test_reconstructor_dataset, test_predictor_dataset, test_sensor_forecaster_dataset)

        return SHRED_train_dataset, SHRED_val_dataset, SHRED_test_dataset


    def postprocess_sensor_measurements(self, data, method, uncompress = True):
        if method == 'sensor_forecaster':
            results = None
        else:
            results = {}
        start_index = 0
        for data_processor in self.data_processors:
            if method == 'sensor_forecaster':
                if data_processor.sensor_measurements is not None:
                    num_sensors = data_processor.sensor_measurements.shape[1]
                    print({start_index},' ',{start_index+num_sensors})
                    result = data[:, start_index:start_index+num_sensors]
                    start_index += start_index
                    result = data_processor.inverse_transform(result, uncompress, method)
                    if results is None:
                        results = result
                    else:
                        results = np.concatenate((results, result), axis=1)
            else:
                field_spatial_dim = data_processor.Y_spatial_dim
                field_data = data[:, start_index:start_index+field_spatial_dim]
                if isinstance(data, torch.Tensor):
                    field_data = field_data.detach().cpu().numpy()
                start_index += field_spatial_dim
                field_data = data_processor.inverse_transform(field_data, uncompress, method)
                results[data_processor.id] = field_data
        return results

    def postprocess(self, data, method, uncompress = True):
        results = {}
        start_index = 0
        for data_processor in self.data_processors:
            field_spatial_dim = data_processor.Y_spatial_dim
            field_data = data[:, start_index:start_index+field_spatial_dim]
            if isinstance(data, torch.Tensor):
                field_data = field_data.detach().cpu().numpy()
            start_index = field_spatial_dim + start_index
            field_data = data_processor.inverse_transform(field_data, uncompress, method)
            results[data_processor.id] = field_data
        return results





    def generate_X(self, method, start = None, end = None, measurements = None, time = None, forecaster=None):
        results = None
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        start_sensor = 0
        # generate lagged sequences using only inputted measurements
        if start is None and end is None and measurements is not None:
            for data_processor in self.data_processors:
                if data_processor.sensor_measurements is not None:
                    end_sensor = start_sensor + data_processor.sensor_measurements.shape[1]
                    field_measurements = measurements[:,start_sensor:end_sensor]
                    result = data_processor.transform_X(field_measurements, method = method)
                    if results is None:
                        results = result
                    else:
                        results = np.concatenate((results, result), axis = 1)
                    start_sensor = end_sensor
            results = generate_lagged_sequences_from_sensor_measurements(results, self.lags)
        else:
            # generate lagged sequences from start to end (inclusive)
            for data_processor in self.data_processors:
                if data_processor.sensor_measurements is not None:
                    end_sensor = start_sensor + data_processor.sensor_measurements.shape[1]
                    # incorporate sensor measurments and associated time provided by user
                    if measurements is not None and time is not None:
                        field_measurements = measurements[:,start_sensor:end_sensor]
                        result = data_processor.generate_X(end = end, measurements = field_measurements, time = time, method = method)
                    else:
                        result = data_processor.generate_X(end = end, measurements = None, time = None, method = method)
                    if results is None:
                        results = result
                    else:
                        results = np.concatenate((results, result), axis = 1)
                    start_sensor = end_sensor
            # extract indices without data (gaps)
            gap_indices = np.where(np.isnan(results).any(axis=1))[0]
            if forecaster is not None:
                for gap in gap_indices:
                    # gap is being forecasted, gap - 1 is 'current'
                    gap_lagged_sequence = results[gap - 1 - self.lags:gap,:].copy()
                    gap_lagged_sequence = gap_lagged_sequence[np.newaxis,:,:]
                    gap_lagged_sequence = torch.tensor(gap_lagged_sequence, dtype=torch.float32, device=device)
                    results[gap] = forecaster(gap_lagged_sequence).detach().cpu().numpy()
            # if no forecaster, replace gaps with zeros
            else:
                results[gap_indices] = 0
            results_sensor_measurements = self.postprocess_sensor_measurements(data = results, method = 'sensor_forecaster')
            results_sensor_measurements = np.concatenate((np.zeros((self.lags, results_sensor_measurements.shape[1])), results_sensor_measurements), axis = 0)
            # print('results_sensor_measurements',results_sensor_measurements.shape)
            # print('start',start)
            # print('end+self.lags+1',end+self.lags+1)
            results_sensor_measurements = results_sensor_measurements[start:end+self.lags+1,:]

            # print('results_sensor_measurements',results_sensor_measurements.shape)
            results = generate_lagged_sequences_from_sensor_measurements(results, self.lags)
            results = results[start:end+1,:,:]

        results = torch.tensor(results, dtype=torch.float32, device=device)
        return {'X': results,
                'sensor_measurements':results_sensor_measurements
                }