from django.test import RequestFactory
from ordenes.views import dashboard_stats, sales_chart_data
from ordenes.models import CustomUser

factory = RequestFactory()
request = factory.get('/api/dashboard-stats/')
# Get the first admin user
user = CustomUser.objects.filter(role__in=['admin', 'auxiliar']).first()
if not user:
    user = CustomUser.objects.first()

request.user = user

try:
    response = dashboard_stats(request)
    print("dashboard_stats response:", response.status_code, response.data)
except Exception as e:
    import traceback
    print("Error in dashboard_stats:")
    traceback.print_exc()

request2 = factory.get('/api/sales-chart-data/')
request2.user = user
try:
    response2 = sales_chart_data(request2)
    print("sales_chart_data response:", response2.status_code, response2.data)
except Exception as e:
    import traceback
    print("Error in sales_chart_data:")
    traceback.print_exc()
