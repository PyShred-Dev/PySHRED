from sklearn.preprocessing import MinMaxScaler, StandardScaler
from sklearn.utils.extmath import randomized_svd
from .utils import *

class SHREDDataProcessor:
    """
    SHREDDataProcessor manages a single dataset.
    SHREDDataProcessor objects are created by the `add` method in SHREDDataManager.
    """

    def __init__(self, data, random_sensors, stationary_sensors, mobile_sensors, lags, time, compression, id):
        """
        Inputs:
        - data: file path to a .npz file. (string)
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
        # Generic
        if compression == True:
            self.n_components = 50
        elif compression == False:
            self.n_components = None
        elif isinstance(compression, int):
            self.n_components = compression
        self.random_sensors = random_sensors # number of randomly placed sensors
        self.stationary_sensors = stationary_sensors # stationary sensor locations
        self.mobile_sensors = mobile_sensors # mobile sensor locations
        self.lags = lags # number of timesteps to look back
        self.compression = compression
        self.sensor_scaler = {}
        self.scaler_before_svd = {}
        self.left_singular_values = {}
        self.singular_values = {}
        self.right_singular_values = {}
        self.scaler = {} # stores scaler of full-state data
        self.sensor_summary = None
        self.sensor_measurements = None
        self.sensor_measurements_pd = None
        self.id = str(id)
        self.Y_spatial_dim = None
        # Specific to SHREDDataProcessor
        self.transformed_sensor_data = {}
        self.transformed_data = {}
        self.full_state_data = get_data(data) # full-state data where the first axis is time (axis 0)
        self.data_spatial_shape = self.full_state_data.shape[1:]
        if time is None:
            self.time = np.arange(self.full_state_data.shape[0]) # numpy array of time stamps associated with `data`
        else:
            self.time = time
        if self.random_sensors is not None or self.stationary_sensors is not None or self.mobile_sensors is not None:
            sensor_measurements_dict = get_sensor_measurements(
                            full_state_data=self.full_state_data,
                            id = self.id,
                            time = self.time,
                            random_sensors = self.random_sensors,
                            stationary_sensors = self.stationary_sensors,
                            mobile_sensors = self.mobile_sensors
                            )
            self.sensor_measurements = sensor_measurements_dict['sensor_measurements'].drop(columns=['time']).to_numpy()
            self.sensor_measurements_pd = sensor_measurements_dict['sensor_measurements']
            self.sensor_summary = sensor_measurements_dict['sensor_summary']



    def generate_dataset(self, train_indices, val_indices, test_indices, method):
        """
        Sets train, val, and test SHREDDataset objects with generated dataset.
        """
        X_train, X_val, X_test = None, None, None
        y_train, y_val, y_test = None, None, None
        is_sensor_forecaster = False
        # Generate X
        if self.sensor_measurements is not None:
            if method == "sensor_forecaster":
                method = "predictor" # sensor_forecaster uses same train_indices as predictor, thus same scalers
                is_sensor_forecaster = True
            scaler = MinMaxScaler()
            self.sensor_scaler[method] = scaler.fit(self.sensor_measurements[train_indices])
            self.transformed_sensor_data[method] = self.sensor_scaler[method].transform(self.sensor_measurements)
            if is_sensor_forecaster is True:
                lagged_sensor_sequences = generate_forecast_lagged_sequences_from_sensor_measurements(self.transformed_sensor_data[method], self.lags)
                X_train = lagged_sensor_sequences[train_indices, :,:]
                y_train = lagged_sensor_sequences[train_indices+1,-1,:]
                X_val = lagged_sensor_sequences[val_indices, :, :]
                y_val = lagged_sensor_sequences[val_indices+1,-1,:]
                X_test = lagged_sensor_sequences[test_indices, :, :]
                y_test = lagged_sensor_sequences[test_indices+1,-1,:]
                return {
                    'train': (X_train, y_train),
                    'val': (X_val, y_val),
                    'test': (X_test, y_test)
                }
            lagged_sensor_sequences = generate_lagged_sequences_from_sensor_measurements(self.transformed_sensor_data[method], self.lags)
            X_train = lagged_sensor_sequences[train_indices]
            X_val = lagged_sensor_sequences[val_indices]
            X_test = lagged_sensor_sequences[test_indices]

        if method == 'reconstructor' or (method == 'predictor' and is_sensor_forecaster is False):
            # Generate Y
            # flattens full state data into into 2D array with time along axis 0.
            self.full_state_data = flatten(self.full_state_data)
            # fit
            self.fit(train_indices, method)
            # transform
            self.transform(method)
            # generate y data
            y_train = self.transformed_data[method][train_indices]
            self.Y_spatial_dim = y_train.shape[1]
            y_val = self.transformed_data[method][val_indices]
            y_test = self.transformed_data[method][test_indices]
            self.full_state_data = unflatten(data = self.full_state_data, spatial_shape=self.data_spatial_shape)
        return {
            'train': (X_train, y_train),
            'val': (X_val, y_val),
            'test': (X_test, y_test)
        }

    def fit(self, train_indices, method):
        """
        Input: train_indices and method ("random" or "sequential")
        Expects self.data to be flattened with time on axis 0.
        Compression: fits standard scaler and save left singular values and singular values
        Stores fitted scalers as object attributes.
        """
        # compression
        if self.n_components is not None:
            # standard scale data
            sc = StandardScaler()
            sc.fit(self.full_state_data[train_indices, :])
            self.scaler_before_svd[method] = sc
            full_state_data_std_scaled = sc.transform(self.full_state_data)
            # rSVD
            U, S, V = randomized_svd(full_state_data_std_scaled[train_indices, :], n_components=self.n_components, n_iter='auto')
            self.right_singular_values[method] = V
            self.left_singular_values[method] = U
            self.singular_values[method] = S
            compressed_full_state_data = full_state_data_std_scaled @ V.transpose()
        scaler = MinMaxScaler()
        if self.n_components is not None:
            self.scaler[method] = scaler.fit(compressed_full_state_data[train_indices])
        else:
            self.scaler[method] = scaler.fit(self.full_state_data[train_indices])

    def transform(self, method):
        """
        Expects self.full_state_data to be flattened with time on axis 0.
        Generates transfomed data which is self.full_state_data compressed (optional) and scaled (optional).
        """
        # Perform compression if all compression-related attributes exist
        if self.right_singular_values.get(method) is not None and self.scaler_before_svd[method] is not None:
            transformed_data = self.scaler_before_svd[method].transform(self.full_state_data)
            transformed_data = transformed_data @ np.transpose(self.right_singular_values.get(method))
        else:
            transformed_data = self.full_state_data
        self.transformed_data[method] = self.scaler[method].transform(transformed_data)


    def inverse_transform(self, data, uncompress, method):
        """
        Expects data to be a np array with time on axis 0.
        (Field specific output fron SHRED/Reconstructor)
        """
        # unscale data if scaler exists
        # (may not exist for sensor_forecaster for some fields)
        if self.scaler.get(method) is not None:
            data = self.scaler[method].inverse_transform(data)
        # uncompress data
        if self.right_singular_values.get(method) is not None and uncompress is True:
            data = data @ self.right_singular_values.get(method)
            data = self.scaler_before_svd[method].inverse_transform(data)
            data = unflatten(data = data, spatial_shape=self.data_spatial_shape)
        return data
    
    def inverse_transform_sensor_measurements(self, data, method):
        if self.sensor_scaler.get(method) is not None:
            data = self.sensor_scaler[method].inverse_transform(data)
        return data


    def generate_X(self, end, measurements, time, method):
        """
        Generates sensor measurements from time = 0
        to time = end. Uses given measurements as
        well as well as stored sensor measurements.
        Gaps are filled with np.nan.
        """
        timesteps = end+1 # end_time inclusive
        nsensors = self.sensor_measurements.shape[1] # make sure measurements dim elf.atches
        complete_measurements = np.full((timesteps, nsensors), np.nan)
        if timesteps > len(self.sensor_measurements):
            complete_measurements[0:len(self.sensor_measurements),:] = self.sensor_measurements
        else:
            complete_measurements[0:timesteps,:] = self.sensor_measurements[0:timesteps,:]
        if measurements is not None and time is not None:
            for i in range(len(time)):
                if time[i] < complete_measurements.shape[0]:
                    complete_measurements[time[i],:] = measurements[i,:]
        complete_measurements = self.sensor_scaler[method].transform(complete_measurements)
        return complete_measurements

    # used for transforming raw new sensor measurements
    def transform_X(self, measurements, method):
        return self.sensor_scaler[method].transform(measurements)


    def discard_data(self):
        self.full_state_data = None
        self.transformed_data = None
        self.transformed_sensor_data = None

