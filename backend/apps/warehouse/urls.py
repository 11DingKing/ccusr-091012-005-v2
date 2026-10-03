"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    GoodsListView, StockInListView, StockOutListView, StockOutCompleteView,
    StockTransferView,
    WarningListView, ApprovalListView,
    QuarantineCaseListView, QuarantineCaseDetailView,
    QuarantineReinspectionView, QuarantineDecisionView,
    QuarantineRevokeDecisionView,
)

urlpatterns = [
    # 单位管理
    path('units/', UnitListView.as_view(), name='unit-list'),
    path('units/all/', UnitAllView.as_view(), name='unit-all'),
    path('units/batch-delete/', UnitBatchDeleteView.as_view(), name='unit-batch-delete'),
    path('units/<int:pk>/', UnitDetailView.as_view(), name='unit-detail'),

    # 品类管理
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('categories/all/', CategoryAllView.as_view(), name='category-all'),
    path('categories/batch-delete/', CategoryBatchDeleteView.as_view(), name='category-batch-delete'),
    path('categories/<int:pk>/', CategoryDetailView.as_view(), name='category-detail'),

    # 品种管理
    path('varieties/', VarietyListView.as_view(), name='variety-list'),
    path('varieties/batch-delete/', VarietyBatchDeleteView.as_view(), name='variety-batch-delete'),
    path('varieties/template/', VarietyTemplateView.as_view(), name='variety-template'),
    path('varieties/import/', VarietyImportView.as_view(), name='variety-import'),
    path('varieties/<int:pk>/', VarietyDetailView.as_view(), name='variety-detail'),

    # 货物管理
    path('goods/', GoodsListView.as_view(), name='goods-list'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 领用管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),
    path('stock-out/<int:pk>/complete/', StockOutCompleteView.as_view(), name='stock-out-complete'),

    # 库位转移
    path('stock-movements/transfer/', StockTransferView.as_view(), name='stock-transfer'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # 隔离处置案件
    path('quarantine-cases/', QuarantineCaseListView.as_view(), name='quarantine-case-list'),
    path('quarantine-cases/<int:pk>/', QuarantineCaseDetailView.as_view(), name='quarantine-case-detail'),
    path('quarantine-cases/<int:pk>/reinspection/', QuarantineReinspectionView.as_view(), name='quarantine-case-reinspection'),
    path('quarantine-cases/<int:pk>/decision/', QuarantineDecisionView.as_view(), name='quarantine-case-decision'),
    path('quarantine-approvals/<int:pk>/revoke/', QuarantineRevokeDecisionView.as_view(), name='quarantine-approval-revoke'),
]
