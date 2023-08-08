import os
import logging

from tqdm import tqdm

from darts import concatenate


# Models
from darts.models import (
    StatsForecastAutoARIMA,
    RNNModel,
    TCNModel,
    NBEATSModel,
    TFTModel,
    RandomForest,
    XGBModel,
    LightGBMModel,
    NHiTSModel,
    TBATS,
    Prophet,
)

# Local imports
from experiment.train_test import get_train_test
from hyperopt.analysis import best_hyperparameters
from config import all_coins, timeframes, n_periods, all_models, ml_models

# Ignore fbprophet warnings
logger = logging.getLogger("cmdstanpy")
logger.addHandler(logging.NullHandler())
logger.propagate = False
logger.setLevel(logging.CRITICAL)


def get_model(model_name, coin, time_frame):
    # TODO: Also add the model unspecific parameters

    if model_name == "ARIMA":
        return StatsForecastAutoARIMA(
            start_p=0,
            start_q=0,
            start_P=0,
            start_Q=0,
            max_p=5,
            max_d=5,
            max_q=5,
            max_P=5,
            max_Q=5,
        )
    elif model_name == "RandomForest":
        return RandomForest(**best_hyperparameters(model_name, coin, time_frame))
    elif model_name == "XGB":
        return XGBModel(**best_hyperparameters(model_name, coin, time_frame))
    elif model_name == "LightGBM":
        return LightGBMModel(**best_hyperparameters(model_name, coin, time_frame))
    elif model_name == "Prophet":
        return Prophet(**best_hyperparameters(model_name, coin, time_frame))
    elif model_name == "TBATS":
        # https://medium.com/analytics-vidhya/time-series-forecasting-using-tbats-model-ce8c429442a9
        return TBATS(
            use_arma_errors=None,
            n_jobs=1,  # Seems to be quicker
        )
    elif model_name == "NBEATS":
        return NBEATSModel(
            **best_hyperparameters(model_name, coin, time_frame), model_name=model_name
        )
    elif model_name == "RNN":
        return RNNModel(
            **best_hyperparameters(model_name, coin, time_frame), model_name=model_name
        )
    elif model_name == "LSTM":
        return RNNModel(
            **best_hyperparameters(model_name, coin, time_frame),
            model_name=model_name,
            model="LSTM",
        )
    elif model_name == "GRU":
        return RNNModel(
            **best_hyperparameters(model_name, coin, time_frame),
            model_name=model_name,
            model="GRU",
        )
    elif model_name == "TCN":
        return TCNModel(
            **best_hyperparameters(model_name, coin, time_frame), model_name=model_name
        )
    elif model_name == "TFT":
        return TFTModel(
            **best_hyperparameters(model_name, coin, time_frame), model_name=model_name
        )
    elif model_name == "NHiTS":
        return NHiTSModel(
            **best_hyperparameters(model_name, coin, time_frame), model_name=model_name
        )
    else:
        raise ValueError(f"Model {model_name} is not supported.")


def generate_forecasts(model_name: str, coin: str, time_frame: str):
    # Get the training and testing data for each period
    train_set, test_set, time_series = get_train_test(
        coin=coin,
        time_frame=time_frame,
        n_periods=n_periods,
    )

    # Certain models need to be retrained for each period
    retrain = False
    train_length = None
    if model_name in ["Prophet", "TBATS", "ARIMA"]:
        retrain = True
        train_length = len(train_set[0])

    for period in tqdm(
        range(n_periods),
        desc=f"Forecasting periods for {model_name}/{coin}/{time_frame}",
        leave=False,
    ):
        # Reset the model
        model = get_model(model_name, coin, time_frame)

        # Fit on the training data
        model.fit(series=train_set[period])

        # Generate the historical forecast
        pred = model.historical_forecasts(
            time_series[period],
            start=len(train_set[period]),
            forecast_horizon=1,  # 1 step ahead forecasting
            stride=1,  # 1 step ahead forecasting
            retrain=retrain,
            train_length=train_length,
            verbose=False,
        )

        # Save all important information
        pred.pd_dataframe().to_csv(
            f"data/models/{model_name}/{coin}/{time_frame}/pred_{period}.csv"
        )
        train_set[period].pd_dataframe().to_csv(
            f"data/models/{model_name}/{coin}/{time_frame}/train_{period}.csv"
        )
        test_set[period].pd_dataframe().to_csv(
            f"data/models/{model_name}/{coin}/{time_frame}/test_{period}.csv"
        )


def generate_extended_forecasts(model_name: str, coin: str, time_frame: str):
    # Get the training and testing data for each period
    train_set, test_set, time_series = get_train_test(
        coin=coin,
        time_frame=time_frame,
    )

    # This will always be used to test on
    final_test = test_set[-1]

    # This will be increased backwards every period
    complete_ts = time_series[-1]

    # Start with the last period
    reversed_periods = reversed(range(n_periods))

    # Start from the final period and add training + test to it
    for period in tqdm(
        reversed_periods,
        desc=f"Forecasting periods for {model_name}/{coin}/{time_frame}",
        leave=False,
    ):
        extended_train = complete_ts[: -len(final_test)]

        # Reset the model
        model = get_model(model_name, coin, time_frame)
        model.fit(series=extended_train)

        pred = model.historical_forecasts(
            complete_ts,
            start=len(complete_ts) - len(final_test),
            forecast_horizon=1,  # 1 step ahead forecasting
            stride=1,  # 1 step ahead forecasting
            retrain=False,
            train_length=None,  # only necessary if retrain=True
            verbose=False,
        )

        # Save all important information
        pred.pd_dataframe().to_csv(
            f"data/extended_models/{model_name}/{coin}/{time_frame}/pred_{period}.csv"
        )
        # The training data keeps increase backwards
        extended_train.pd_dataframe().to_csv(
            f"data/extended_models/{model_name}/{coin}/{time_frame}/train_{period}.csv"
        )
        # Test set is always the same
        final_test.pd_dataframe().to_csv(
            f"data/extended_models/{model_name}/{coin}/{time_frame}/test_{period}.csv"
        )

        # Period 0 is last, meaning this model used the most training data
        if period == 0:
            break

        # Increase the complete time series, add it to the front of current
        # Time series shifts with the length of the test set
        complete_ts = concatenate(
            [train_set[period - 1][: len(test_set[0])], complete_ts], axis=0
        )


def generate_raw_forecasts(model_name: str, coin: str, time_frame: str):
    # Get the training and testing data for each period
    train_set, test_set, time_series = get_train_test(
        coin=coin, time_frame=time_frame, n_periods=n_periods, col="close"
    )

    # Certain models need to be retrained for each period
    retrain = False
    train_length = None
    if model_name in ["Prophet", "TBATS", "ARIMA"]:
        retrain = True
        train_length = len(train_set[0])

    for period in tqdm(
        range(n_periods),
        desc=f"Forecasting periods for {model_name}/{coin}/{time_frame}",
        leave=False,
    ):
        # Reset the model
        model = get_model(model_name, coin, time_frame)

        # Fit on the training data
        model.fit(series=train_set[period])

        # Generate the historical forecast
        pred = model.historical_forecasts(
            time_series[period],
            start=len(train_set[period]),
            forecast_horizon=1,  # 1 step ahead forecasting
            stride=1,  # 1 step ahead forecasting
            retrain=retrain,
            train_length=train_length,
            verbose=False,
        )

        # Save all important information
        pred.pd_dataframe().to_csv(
            f"data/raw_models/{model_name}/{coin}/{time_frame}/pred_{period}.csv"
        )
        train_set[period].pd_dataframe().to_csv(
            f"data/raw_models/{model_name}/{coin}/{time_frame}/train_{period}.csv"
        )
        test_set[period].pd_dataframe().to_csv(
            f"data/raw_models/{model_name}/{coin}/{time_frame}/test_{period}.csv"
        )


def raw_forecast_model(model_name, start_from_coin="BTC", start_from_time_frame="1m"):
    for coin in all_coins[all_coins.index(start_from_coin) :]:
        for time_frame in timeframes[timeframes.index(start_from_time_frame) :]:
            # Create directories
            os.makedirs(
                f"data/raw_models/{model_name}/{coin}/{time_frame}", exist_ok=True
            )

            generate_raw_forecasts(model_name, coin, time_frame)


def raw_all(
    start_from_model=None,
    start_from_coin=None,
    start_from_time_frame=None,
    ignore_model=[],
):
    models = all_models

    if start_from_model:
        models = models[models.index(start_from_model) :]

    for model in tqdm(models, desc="Generating forecast for all models", leave=False):
        if model in ignore_model:
            continue

        coin = "BTC"
        time_frame = "1m"

        if start_from_coin and start_from_model == model:
            coin = start_from_coin
            if start_from_time_frame:
                time_frame = start_from_time_frame

        raw_forecast_model(model, coin, time_frame)


def extended_forecast_model(
    model_name, start_from_coin="BTC", start_from_time_frame="1m"
):
    for coin in all_coins[all_coins.index(start_from_coin) :]:
        for time_frame in timeframes[timeframes.index(start_from_time_frame) :]:
            # Create directories
            os.makedirs(
                f"data/extended_models/{model_name}/{coin}/{time_frame}", exist_ok=True
            )

            generate_extended_forecasts(model_name, coin, time_frame)


def extend_all(
    start_from_model=None,
    start_from_coin=None,
    start_from_time_frame=None,
    ignore_model=[],
):
    # All ML models
    models = ml_models

    if start_from_model:
        models = models[models.index(start_from_model) :]

    for model in tqdm(models, desc="Generating forecast for all models", leave=False):
        if model in ignore_model:
            continue

        coin = "BTC"
        time_frame = "1m"

        if start_from_coin and start_from_model == model:
            coin = start_from_coin
            if start_from_time_frame:
                time_frame = start_from_time_frame

        extended_forecast_model(model, coin, time_frame)


def forecast_model(model_name, start_from_coin="BTC", start_from_time_frame="1m"):
    for coin in all_coins[all_coins.index(start_from_coin) :]:
        for time_frame in timeframes[timeframes.index(start_from_time_frame) :]:
            # Create directories
            os.makedirs(f"data/models/{model_name}/{coin}/{time_frame}", exist_ok=True)

            generate_forecasts(model_name, coin, time_frame)


def forecast_all(
    start_from_model=None,
    start_from_coin=None,
    start_from_time_frame=None,
    ignore_model=[],
):
    models = all_models

    if start_from_model:
        models = models[models.index(start_from_model) :]

    for model in tqdm(models, desc="Generating forecast for all models", leave=False):
        if model in ignore_model:
            continue

        coin = "BTC"
        time_frame = "1m"

        if start_from_coin and start_from_model == model:
            coin = start_from_coin
            if start_from_time_frame:
                time_frame = start_from_time_frame

        forecast_model(model, coin, time_frame)


def test_models():
    for model in all_models:
        for coin in all_coins:
            for time_frame in timeframes:
                print(f"Testing {model} for {coin} {time_frame}")
                get_model(model, coin, time_frame)


def find_missing_forecasts(folder_name, models=[]):
    all_models = all_models

    if models:
        all_models = models

    missing = []

    for model_name in all_models:
        for coin in all_coins:
            for time_frame in timeframes:
                for period in range(5):
                    file_path = f"data/{folder_name}/{model_name}/{coin}/{time_frame}/pred_{period}.csv"
                    if not os.path.exists(file_path):
                        missing.append((model_name, coin, time_frame))
                        print(f"Missing {file_path}")
                        break

    print(f"Found {len(missing)} missing forecasts.")

    if not missing:
        print("No missing forecasts found.")

    return missing


def create_missing_forecasts(folder_name="models", models=[]):
    if folder_name == "models":
        generate_func = generate_forecasts
    elif folder_name == "raw_models":
        generate_func = generate_raw_forecasts
    elif folder_name == "extended_models":
        generate_func = generate_extended_forecasts

    # Create directory
    for model_name, coin, time_frame in find_missing_forecasts(folder_name, models):
        os.makedirs(
            f"data/{folder_name}/{model_name}/{coin}/{time_frame}/",
            exist_ok=True,
        )

        generate_func(model_name, coin, time_frame)
