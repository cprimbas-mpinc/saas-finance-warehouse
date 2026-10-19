{% test control_has_no_exceptions(model) %}
-- A control model returns only exception rows; any row is a failure that needs follow-up.
select * from {{ model }}
{% endtest %}
