"""
仓库管理URL配置
"""
from django.urls import path
from .views import (
    UnitListView, UnitDetailView, UnitBatchDeleteView, UnitAllView,
    CategoryListView, CategoryDetailView, CategoryBatchDeleteView, CategoryAllView,
    VarietyListView, VarietyDetailView, VarietyBatchDeleteView,
    VarietyTemplateView, VarietyImportView,
    DashboardView, GoodsListView, GoodsTransferView,
    StockInListView, StockOutListView,
    WarningListView, ApprovalListView,
    QuarantineCaseListView, QuarantineCaseDetailView,
    QuarantineInspectionListView,
    QuarantineDecisionListView, QuarantineDecisionReviewView,
    QuarantineDecisionRevokeView,
)

urlpatterns = [
    # 仪表盘
    path('dashboard/', DashboardView.as_view(), name='dashboard'),

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
    path('goods/<int:pk>/transfer/', GoodsTransferView.as_view(), name='goods-transfer'),

    # 入库管理
    path('stock-in/', StockInListView.as_view(), name='stock-in-list'),

    # 出库管理
    path('stock-out/', StockOutListView.as_view(), name='stock-out-list'),

    # 预警管理
    path('warnings/', WarningListView.as_view(), name='warning-list'),

    # 审批管理
    path('approvals/', ApprovalListView.as_view(), name='approval-list'),

    # 隔离处置
    path('quarantine-cases/', QuarantineCaseListView.as_view(), name='quarantine-case-list'),
    path('quarantine-cases/<int:pk>/', QuarantineCaseDetailView.as_view(), name='quarantine-case-detail'),
    path('quarantine-cases/<int:case_id>/inspections/', QuarantineInspectionListView.as_view(), name='quarantine-inspection-list'),
    path('quarantine-cases/<int:case_id>/decisions/', QuarantineDecisionListView.as_view(), name='quarantine-case-decision-create'),
    path('quarantine-decisions/', QuarantineDecisionListView.as_view(), name='quarantine-decision-list'),
    path('quarantine-decisions/<int:pk>/review/', QuarantineDecisionReviewView.as_view(), name='quarantine-decision-review'),
    path('quarantine-decisions/<int:pk>/revoke/', QuarantineDecisionRevokeView.as_view(), name='quarantine-decision-revoke'),
]
