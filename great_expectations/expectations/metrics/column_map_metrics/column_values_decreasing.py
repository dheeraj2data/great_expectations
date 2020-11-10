from typing import Any, Dict, Optional, Tuple

from great_expectations.core import ExpectationConfiguration
from great_expectations.execution_engine import (
    ExecutionEngine,
    PandasExecutionEngine,
    SparkDFExecutionEngine,
)
from great_expectations.expectations.metrics.column_map_metric import (
    ColumnMapMetricProvider,
    column_map_condition,
)
from great_expectations.expectations.metrics.import_manager import F, Window, sparktypes
from great_expectations.expectations.metrics.metric_provider import metric
from great_expectations.validator.validation_graph import MetricConfiguration


class ColumnValuesDecreasing(ColumnMapMetricProvider):
    condition_metric_name = "column_values.decreasing"
    condition_value_keys = ("strictly",)
    default_kwarg_values = {"strictly": False}

    @column_map_condition(engine=PandasExecutionEngine)
    def _pandas(cls, column, strictly, **kwargs):
        series_diff = column.diff()
        # The first element is null, so it gets a bye and is always treated as True
        series_diff[series_diff.isnull()] = -1

        if strictly:
            return series_diff < 0
        else:
            return series_diff <= 0

    # @column_map_condition(engine=SparkDFExecutionEngine, metric_fn_type="window_condition_fn")
    # def _spark(cls, column, strictly, _metrics, _accessor_domain_kwargs, _table, **kwargs):
    @metric(
        engine=SparkDFExecutionEngine,
        metric_fn_type="window_condition_fn",
        domain_type="column",
    )
    def _spark(
        cls,
        execution_engine: SparkDFExecutionEngine,
        metric_domain_kwargs: Dict,
        metric_value_kwargs: Dict,
        metrics: Dict[Tuple, Any],
        runtime_configuration: Dict,
    ):
        # check if column is any type that could have na (numeric types)
        column_name = metric_domain_kwargs["column"]
        table_columns = metrics["table.column_types"]
        column_metadata = [col for col in table_columns if col["name"] == column_name][
            0
        ]
        if isinstance(
            column_metadata["type"],
            (sparktypes.LongType, sparktypes.DoubleType, sparktypes.IntegerType,),
        ):
            # if column is any type that could have NA values, remove them (not filtered by .isNotNull())
            compute_domain_kwargs = execution_engine.add_column_row_condition(
                metric_domain_kwargs,
                filter_null=cls.filter_column_isnull,
                filter_nan=True,
            )
        else:
            compute_domain_kwargs = metric_domain_kwargs

        (
            df,
            compute_domain_kwargs,
            accessor_domain_kwargs,
        ) = execution_engine.get_compute_domain(compute_domain_kwargs)

        # NOTE: 20201105 - parse_strings_as_datetimes is not supported here;
        # instead detect types naturally
        column = F.col(column_name)
        if isinstance(
            column_metadata["type"], (sparktypes.TimestampType, sparktypes.DateType)
        ):
            diff = F.datediff(
                column, F.lag(column).over(Window.orderBy(F.lit("constant")))
            )
        else:
            diff = column - F.lag(column).over(Window.orderBy(F.lit("constant")))
            diff = F.when(diff.isNull(), -1).otherwise(diff)

        if metric_value_kwargs["strictly"]:
            return (
                F.when(diff >= -1, F.lit(True)).otherwise(F.lit(False)),
                compute_domain_kwargs,
            )

        else:
            return (
                F.when(diff >= 0, F.lit(True)).otherwise(F.lit(False)),
                compute_domain_kwargs,
            )

    @classmethod
    def get_evaluation_dependencies(
        cls,
        metric: MetricConfiguration,
        configuration: Optional[ExpectationConfiguration] = None,
        execution_engine: Optional[ExecutionEngine] = None,
        runtime_configuration: Optional[dict] = None,
    ):
        if (
            isinstance(execution_engine, SparkDFExecutionEngine)
            and metric.metric_name == "column_values.decreasing"
        ):
            return {
                "table.column_types": MetricConfiguration(
                    "table.column_types",
                    metric.metric_domain_kwargs,
                    {"include_nested": True},
                )
            }
        else:
            return super().get_evaluation_dependencies(
                metric=metric,
                configuration=configuration,
                execution_engine=execution_engine,
                runtime_configuration=runtime_configuration,
            )
