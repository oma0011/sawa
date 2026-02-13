"""
Nigerian Payroll Engine - Production Version
Handles all payroll calculations with 2026 PAYE compliance
"""

from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from typing import Optional, Dict, List
from datetime import datetime, date
from enum import Enum


class EmploymentType(Enum):
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERN = "intern"


@dataclass
class EmployeeSalaryStructure:
    """Employee salary components"""
    employee_id: str
    employee_name: str
    basic_salary: Decimal
    housing_allowance: Decimal = Decimal('0')
    transport_allowance: Decimal = Decimal('0')
    meal_allowance: Decimal = Decimal('0')
    utility_allowance: Decimal = Decimal('0')
    other_allowances: Decimal = Decimal('0')
    bonus: Decimal = Decimal('0')
    overtime: Decimal = Decimal('0')
    
    # Deductions
    loan_repayment: Decimal = Decimal('0')
    other_deductions: Decimal = Decimal('0')
    
    # Employment details
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    days_worked: Optional[int] = None  # For prorated calculations
    total_days: int = 30


@dataclass
class PayrollResult:
    """Complete payroll calculation result"""
    employee_id: str
    employee_name: str
    period_start: date
    period_end: date
    
    # Earnings
    basic_salary: Decimal
    housing_allowance: Decimal
    transport_allowance: Decimal
    meal_allowance: Decimal
    utility_allowance: Decimal
    other_allowances: Decimal
    bonus: Decimal
    overtime: Decimal
    gross_salary: Decimal
    
    # Statutory Deductions
    pension_employee: Decimal  # 8%
    pension_employer: Decimal  # 10%
    nhf: Decimal  # 2.5%
    paye: Decimal
    
    # Other Deductions
    loan_repayment: Decimal
    other_deductions: Decimal
    total_deductions: Decimal
    
    # Net Pay
    net_salary: Decimal
    
    # Tax Calculation Details
    annual_gross: Decimal
    rent_relief: Decimal
    taxable_income: Decimal
    annual_paye: Decimal
    
    # Metadata
    is_prorated: bool
    calculation_notes: List[str]


class NigerianPayrollEngine:
    """
    Production-grade Nigerian Payroll Engine
    Implements all FIRS, PenCom, and NHF regulations
    """
    
    # 2026 PAYE Tax Brackets (Annual)
    TAX_BRACKETS = [
        (Decimal('800000'), Decimal('0.00')),      # First ₦800k: 0%
        (Decimal('2200000'), Decimal('0.15')),     # Next ₦2.2M: 15%
        (Decimal('9000000'), Decimal('0.18')),     # Next ₦9M: 18%
        (Decimal('13000000'), Decimal('0.21')),    # Next ₦13M: 21%
        (Decimal('25000000'), Decimal('0.23')),    # Next ₦25M: 23%
        (Decimal('999999999'), Decimal('0.25'))    # Above ₦50M: 25%
    ]
    
    # Relief and Rates
    RENT_RELIEF_RATE = Decimal('0.20')  # 20% of gross
    RENT_RELIEF_CAP = Decimal('500000')  # Annual cap
    
    PENSION_EMPLOYEE_RATE = Decimal('0.08')  # 8%
    PENSION_EMPLOYER_RATE = Decimal('0.10')  # 10%
    NHF_RATE = Decimal('0.025')  # 2.5%
    NHF_MINIMUM_SALARY = Decimal('3000')  # Monthly minimum for NHF
    
    # NSITF and ITF (Employer-only, not deducted from employee)
    NSITF_RATE = Decimal('0.01')  # 1% of total payroll
    ITF_RATE = Decimal('0.01')  # 1% of total payroll
    
    def __init__(self):
        self.calculation_precision = Decimal('0.01')
    
    def _round_money(self, amount: Decimal) -> Decimal:
        """Round to 2 decimal places"""
        return amount.quantize(self.calculation_precision, rounding=ROUND_HALF_UP)
    
    def calculate_gross_salary(self, salary_structure: EmployeeSalaryStructure) -> Decimal:
        """Calculate total gross salary"""
        gross = (
            salary_structure.basic_salary +
            salary_structure.housing_allowance +
            salary_structure.transport_allowance +
            salary_structure.meal_allowance +
            salary_structure.utility_allowance +
            salary_structure.other_allowances +
            salary_structure.bonus +
            salary_structure.overtime
        )
        
        # Apply proration if needed
        if salary_structure.days_worked and salary_structure.days_worked < salary_structure.total_days:
            proration_factor = Decimal(salary_structure.days_worked) / Decimal(salary_structure.total_days)
            gross = gross * proration_factor
        
        return self._round_money(gross)
    
    def calculate_pensionable_income(self, salary_structure: EmployeeSalaryStructure) -> Decimal:
        """
        Calculate pensionable income
        PenCom: Pension is on Basic + Housing + Transport only
        """
        pensionable = (
            salary_structure.basic_salary +
            salary_structure.housing_allowance +
            salary_structure.transport_allowance
        )
        
        # Apply proration if needed
        if salary_structure.days_worked and salary_structure.days_worked < salary_structure.total_days:
            proration_factor = Decimal(salary_structure.days_worked) / Decimal(salary_structure.total_days)
            pensionable = pensionable * proration_factor
        
        return self._round_money(pensionable)
    
    def calculate_pension_contribution(
        self, 
        pensionable_income: Decimal,
        rate: Decimal
    ) -> Decimal:
        """Calculate pension contribution"""
        return self._round_money(pensionable_income * rate)
    
    def calculate_nhf_contribution(self, basic_salary: Decimal, is_prorated: bool = False) -> Decimal:
        """
        Calculate NHF contribution
        Only applicable if basic salary >= ₦3,000/month
        """
        if basic_salary < self.NHF_MINIMUM_SALARY:
            return Decimal('0')
        
        return self._round_money(basic_salary * self.NHF_RATE)
    
    def calculate_rent_relief(self, gross_annual: Decimal) -> Decimal:
        """
        Calculate rent relief: 20% of gross, capped at ₦500k annually
        """
        relief = gross_annual * self.RENT_RELIEF_RATE
        return min(relief, self.RENT_RELIEF_CAP)
    
    def calculate_annual_paye(self, taxable_income_annual: Decimal) -> Decimal:
        """
        Calculate annual PAYE using progressive tax brackets.
        Each bracket value is the bracket SIZE (not cumulative threshold).
        """
        remaining_income = taxable_income_annual
        total_tax = Decimal('0')

        for bracket_size, tax_rate in self.TAX_BRACKETS:
            if remaining_income <= 0:
                break
            taxable_in_bracket = min(remaining_income, bracket_size)
            total_tax += taxable_in_bracket * tax_rate
            remaining_income -= taxable_in_bracket

        return self._round_money(total_tax)
    
    def calculate_payroll(
        self,
        salary_structure: EmployeeSalaryStructure,
        period_start: date,
        period_end: date
    ) -> PayrollResult:
        """
        Calculate complete payroll for an employee
        """
        notes = []
        
        # 1. Calculate gross salary
        gross_monthly = self.calculate_gross_salary(salary_structure)
        
        # Check for proration
        is_prorated = (
            salary_structure.days_worked is not None and 
            salary_structure.days_worked < salary_structure.total_days
        )
        
        if is_prorated:
            notes.append(
                f"Prorated for {salary_structure.days_worked}/{salary_structure.total_days} days"
            )

        # 2. Calculate annual gross (for tax purposes)
        # Use FULL monthly salary for annualization, not the prorated amount
        if is_prorated:
            gross_full_monthly = (
                salary_structure.basic_salary +
                salary_structure.housing_allowance +
                salary_structure.transport_allowance +
                salary_structure.meal_allowance +
                salary_structure.utility_allowance +
                salary_structure.other_allowances +
                salary_structure.bonus +
                salary_structure.overtime
            )
            gross_annual = self._round_money(gross_full_monthly) * Decimal('12')
        else:
            gross_annual = gross_monthly * Decimal('12')
        
        # 3. Calculate pensionable income
        pensionable_income = self.calculate_pensionable_income(salary_structure)
        
        # 4. Calculate pension contributions
        pension_employee_monthly = self.calculate_pension_contribution(
            pensionable_income,
            self.PENSION_EMPLOYEE_RATE
        )
        pension_employee_annual = pension_employee_monthly * Decimal('12')
        
        pension_employer_monthly = self.calculate_pension_contribution(
            pensionable_income,
            self.PENSION_EMPLOYER_RATE
        )
        
        # 5. Calculate NHF
        basic_for_nhf = salary_structure.basic_salary
        if is_prorated:
            proration_factor = Decimal(salary_structure.days_worked) / Decimal(salary_structure.total_days)
            basic_for_nhf = basic_for_nhf * proration_factor
        
        nhf_monthly = self.calculate_nhf_contribution(basic_for_nhf, is_prorated)
        nhf_annual = nhf_monthly * Decimal('12')
        
        if nhf_monthly == 0 and basic_for_nhf < self.NHF_MINIMUM_SALARY:
            notes.append(f"NHF not applicable (basic < ₦{self.NHF_MINIMUM_SALARY})")
        
        # 6. Calculate rent relief
        rent_relief_annual = self.calculate_rent_relief(gross_annual)
        
        # 7. Calculate taxable income
        taxable_income_annual = gross_annual - pension_employee_annual - nhf_annual - rent_relief_annual
        
        # Ensure taxable income is not negative
        if taxable_income_annual < 0:
            taxable_income_annual = Decimal('0')
            notes.append("Taxable income is zero after deductions")
        
        # 8. Calculate PAYE
        paye_annual = self.calculate_annual_paye(taxable_income_annual)
        paye_monthly = self._round_money(paye_annual / Decimal('12'))

        # If prorated, scale down the monthly PAYE proportionally
        if is_prorated:
            proration_factor = Decimal(salary_structure.days_worked) / Decimal(salary_structure.total_days)
            paye_monthly = self._round_money(paye_monthly * proration_factor)
        
        if paye_monthly == 0:
            notes.append("No PAYE tax (below threshold or fully relieved)")
        
        # 9. Calculate total deductions
        total_deductions = (
            pension_employee_monthly +
            nhf_monthly +
            paye_monthly +
            salary_structure.loan_repayment +
            salary_structure.other_deductions
        )
        
        # 10. Calculate net salary
        net_salary = gross_monthly - total_deductions
        
        # Create result
        return PayrollResult(
            employee_id=salary_structure.employee_id,
            employee_name=salary_structure.employee_name,
            period_start=period_start,
            period_end=period_end,
            
            # Earnings
            basic_salary=self._round_money(salary_structure.basic_salary),
            housing_allowance=self._round_money(salary_structure.housing_allowance),
            transport_allowance=self._round_money(salary_structure.transport_allowance),
            meal_allowance=self._round_money(salary_structure.meal_allowance),
            utility_allowance=self._round_money(salary_structure.utility_allowance),
            other_allowances=self._round_money(salary_structure.other_allowances),
            bonus=self._round_money(salary_structure.bonus),
            overtime=self._round_money(salary_structure.overtime),
            gross_salary=gross_monthly,
            
            # Statutory Deductions
            pension_employee=pension_employee_monthly,
            pension_employer=pension_employer_monthly,
            nhf=nhf_monthly,
            paye=paye_monthly,
            
            # Other Deductions
            loan_repayment=salary_structure.loan_repayment,
            other_deductions=salary_structure.other_deductions,
            total_deductions=total_deductions,
            
            # Net Pay
            net_salary=net_salary,
            
            # Tax Details
            annual_gross=gross_annual,
            rent_relief=rent_relief_annual,
            taxable_income=taxable_income_annual,
            annual_paye=paye_annual,
            
            # Metadata
            is_prorated=is_prorated,
            calculation_notes=notes
        )
    
    def generate_payslip(self, result: PayrollResult) -> str:
        """Generate formatted payslip"""
        def fmt(amount: Decimal) -> str:
            return f"₦{amount:,.2f}"
        
        lines = [
            "=" * 60,
            f"PAYSLIP - {result.employee_name}",
            f"Employee ID: {result.employee_id}",
            f"Period: {result.period_start.strftime('%d %b %Y')} - {result.period_end.strftime('%d %b %Y')}",
            "=" * 60,
            "",
            "EARNINGS:",
            f"  Basic Salary:           {fmt(result.basic_salary)}",
            f"  Housing Allowance:      {fmt(result.housing_allowance)}",
            f"  Transport Allowance:    {fmt(result.transport_allowance)}",
            f"  Meal Allowance:         {fmt(result.meal_allowance)}",
            f"  Utility Allowance:      {fmt(result.utility_allowance)}",
            f"  Other Allowances:       {fmt(result.other_allowances)}",
            f"  Bonus:                  {fmt(result.bonus)}",
            f"  Overtime:               {fmt(result.overtime)}",
            f"  {'─' * 58}",
            f"  GROSS SALARY:           {fmt(result.gross_salary)}",
            "",
            "DEDUCTIONS:",
            f"  Pension (8%):           {fmt(result.pension_employee)}",
            f"  NHF (2.5%):            {fmt(result.nhf)}",
            f"  PAYE Tax:              {fmt(result.paye)}",
            f"  Loan Repayment:        {fmt(result.loan_repayment)}",
            f"  Other Deductions:      {fmt(result.other_deductions)}",
            f"  {'─' * 58}",
            f"  TOTAL DEDUCTIONS:      {fmt(result.total_deductions)}",
            "",
            "=" * 60,
            f"NET SALARY:              {fmt(result.net_salary)}",
            "=" * 60,
            "",
            "EMPLOYER CONTRIBUTIONS:",
            f"  Pension (10%):         {fmt(result.pension_employer)}",
            "",
            "TAX CALCULATION SUMMARY:",
            f"  Annual Gross Income:   {fmt(result.annual_gross)}",
            f"  Rent Relief (20%):     {fmt(result.rent_relief)}",
            f"  Annual Taxable Income: {fmt(result.taxable_income)}",
            f"  Annual PAYE Tax:       {fmt(result.annual_paye)}",
            ""
        ]
        
        if result.is_prorated:
            lines.append("* Salary prorated for partial month")
        
        if result.calculation_notes:
            lines.append("")
            lines.append("NOTES:")
            for note in result.calculation_notes:
                lines.append(f"  • {note}")
        
        lines.extend([
            "",
            "=" * 60,
            f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}",
            "=" * 60
        ])
        
        return "\n".join(lines)


# Example usage
if __name__ == "__main__":
    from datetime import date
    
    engine = NigerianPayrollEngine()
    
    # Example 1: Regular employee
    print("\n### EXAMPLE 1: Regular Full-Time Employee ###\n")
    
    employee1 = EmployeeSalaryStructure(
        employee_id="EMP001",
        employee_name="Ngozi Adeyemi",
        basic_salary=Decimal('200000'),
        housing_allowance=Decimal('100000'),
        transport_allowance=Decimal('50000'),
        other_allowances=Decimal('50000')
    )
    
    result1 = engine.calculate_payroll(
        employee1,
        date(2026, 1, 1),
        date(2026, 1, 31)
    )
    
    print(engine.generate_payslip(result1))
    
    # Example 2: Prorated salary (employee joined mid-month)
    print("\n\n### EXAMPLE 2: Prorated Salary (Joined 15th Jan) ###\n")
    
    employee2 = EmployeeSalaryStructure(
        employee_id="EMP002",
        employee_name="Chidi Okafor",
        basic_salary=Decimal('150000'),
        housing_allowance=Decimal('75000'),
        transport_allowance=Decimal('25000'),
        days_worked=17,  # Joined on 15th, worked 17 days
        total_days=31
    )
    
    result2 = engine.calculate_payroll(
        employee2,
        date(2026, 1, 1),
        date(2026, 1, 31)
    )
    
    print(engine.generate_payslip(result2))
