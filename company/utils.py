from collections import Counter
from typing import Iterable, List

from django.db.models import Count

from horilla.methods import get_horilla_model_class


def build_company_hierarchy(company_list: Iterable) -> List[dict]:
    """
    Return a nested structure of companies and their children for template rendering.
    """

    nodes = {company.id: {"company": company, "children": []} for company in company_list}
    roots = []

    for company in company_list:
        parent_id = company.parent_company_id
        node = nodes.get(company.id)
        if not node:
            continue
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    def sort_children(node):
        node["children"].sort(key=lambda child: child["company"].company.lower())
        for child in node["children"]:
            sort_children(child)

    for root in roots:
        sort_children(root)

    roots.sort(key=lambda root: root["company"].company.lower())
    return roots


def annotate_company_metrics(company_list: List) -> None:
    """
    Attach employee count, sub-company count and root name details to companies.
    """

    if not company_list:
        return

    company_ids = [company.id for company in company_list if company.id]
    if not company_ids:
        return

    EmployeeWorkInformation = get_horilla_model_class(
        app_label="employee", model="employeeworkinformation"
    )

    employee_counts = (
        EmployeeWorkInformation.objects.entire()
        .filter(
            company_id__in=company_ids,
            employee_id__is_active=True,
        )
        .values("company_id")
        .annotate(total=Count("id"))
    )
    employee_count_map = {item["company_id"]: item["total"] for item in employee_counts}
    sub_company_counter = Counter(
        company.parent_company_id
        for company in company_list
        if company.parent_company_id
    )

    parent_name_cache = {}

    def resolve_root_name(company):
        if company is None:
            return ""
        if company.id in parent_name_cache:
            return parent_name_cache[company.id]
        if not company.parent_company:
            parent_name_cache[company.id] = company.company
            return company.company
        parent_name = resolve_root_name(company.parent_company)
        parent_name_cache[company.id] = parent_name
        return parent_name

    for company in company_list:
        company.employee_count = employee_count_map.get(company.id, 0)
        company.sub_company_count = (
            sub_company_counter.get(company.id, 0)
            if company.parent_company_id is None
            else None
        )
        company.root_company_name = resolve_root_name(company)

