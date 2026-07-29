#!/usr/bin/env python3
"""
Generate diverse Financial Agent examples covering all phases and decision branches for manager presentation.

This script:
1. Analyzes F_CLM_TRANSACTION to find members in DEDUCTIBLE, INITIAL_COVERAGE, and CATASTROPHIC phases
2. Runs Financial Agent with diverse member_id/plan/drug combinations
3. Produces examples showing all decision branches (cheaper, more_expensive, same_cost, not_covered, unpriceable, etc.)
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
sys.path.insert(0, os.path.dirname(__file__))

from agents.financial_agent import financial_agent_for_candidates
import asyncio

def load_data():
    """Load all necessary data files."""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    claims_df = pd.read_csv(os.path.join(data_dir, 'F_CLM_TRANSACTION.csv'))
    plans_df = pd.read_csv(os.path.join(data_dir, 'v_d_plan.csv'))
    pricing_df = pd.read_csv(os.path.join(data_dir, 'v_d_drug_pricing.csv'))
    member_df = pd.read_csv(os.path.join(data_dir, 'v_d_member.csv'))
    
    # Convert date columns
    claims_df['FILLED_DT'] = pd.to_datetime(claims_df['FILLED_DT'])
    pricing_df['PRICE_EFF_FROM_DT'] = pd.to_datetime(pricing_df['PRICE_EFF_FROM_DT'])
    pricing_df['PRICE_EFF_THRU_DT'] = pd.to_datetime(pricing_df['PRICE_EFF_THRU_DT'])
    
    return claims_df, plans_df, pricing_df, member_df

def analyze_member_phases():
    """Analyze members to find those in different insurance phases."""
    claims_df, plans_df, pricing_df, member_df = load_data()
    
    # For 2025-06-01 reference date, calculate YTD OOP for each member
    reference_date = pd.to_datetime('2025-06-01')
    year_start = pd.to_datetime('2025-01-01')
    
    ytd_claims = claims_df[
        (claims_df['FILLED_DT'] >= year_start) & 
        (claims_df['FILLED_DT'] <= reference_date) &
        (claims_df['CLAIM_STAT_ID'] == 'PAID')
    ].copy()
    
    # Group by member and plan to get YTD OOP
    member_phase_map = {}
    for mbr_sk, member_claims in ytd_claims.groupby('MBR_SK'):
        for pln_sk, plan_claims in member_claims.groupby('PLN_SK'):
            ytd_oop = plan_claims['OOP_APPLIED_AMT'].sum()
            plan_row = plans_df[plans_df['PLN_SK'] == pln_sk].iloc[0] if len(plans_df[plans_df['PLN_SK'] == pln_sk]) > 0 else None
            
            if plan_row is not None:
                deductible = plan_row['DEDUCTIBLE_AMT']
                oop_max = plan_row['MAX_OOP_AMT']
                
                phase = 'INITIAL_COVERAGE'
                if ytd_oop < deductible:
                    phase = 'DEDUCTIBLE'
                elif ytd_oop >= oop_max:
                    phase = 'CATASTROPHIC'
                
                key = (mbr_sk, pln_sk)
                member_phase_map[key] = {
                    'ytd_oop': ytd_oop,
                    'deductible': deductible,
                    'oop_max': oop_max,
                    'phase': phase,
                    'plan_id': pln_sk
                }
    
    return member_phase_map, ytd_claims, plans_df

def get_sample_member_for_phase(phase, member_phase_map):
    """Get a sample member in the requested phase."""
    candidates = [(k, v) for k, v in member_phase_map.items() if v['phase'] == phase]
    if candidates:
        # Prefer members with multiple claims/higher YTD OOP for richer context
        candidates.sort(key=lambda x: x[1]['ytd_oop'], reverse=True)
        return candidates[0]
    return None

def generate_examples():
    """Generate comprehensive Financial Agent examples."""
    print("=" * 80)
    print("FINANCIAL AGENT EXAMPLE GENERATOR FOR MANAGER PRESENTATION")
    print("=" * 80)
    print()
    
    member_phase_map, ytd_claims, plans_df = analyze_member_phases()
    
    # Find representative members for each phase
    print("Analyzing member phases...")
    print(f"  Found {len(member_phase_map)} member-plan combinations with YTD OOP data")
    
    examples = []
    
    # Example 1: DEDUCTIBLE Phase (member hasn't met deductible yet)
    print("\n[1] Finding DEDUCTIBLE phase example...")
    deductible_member = get_sample_member_for_phase('DEDUCTIBLE', member_phase_map)
    if deductible_member:
        (mbr_sk, pln_sk), phase_info = deductible_member
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}, Deductible ${phase_info['deductible']:.2f}")
        
        # Get original drug filled by this member
        member_claims = ytd_claims[ytd_claims['MBR_SK'] == mbr_sk]
        if len(member_claims) > 0:
            orig_drug = member_claims.iloc[0]['PROD_SK']
            
            try:
                result = asyncio.run(financial_agent_for_candidates(
                    payload={
                        'drug_id': str(orig_drug),
                        'plan_id': str(pln_sk),
                        'fill_date': '2025-06-01',
                        'member_id': str(mbr_sk)
                    },
                    candidate_ids=['1033', '1011']  # Use cheaper alternatives
                ))
                examples.append({
                    'phase': 'DEDUCTIBLE',
                    'member_id': mbr_sk,
                    'plan_id': pln_sk,
                    'original_drug': orig_drug,
                    'ytd_oop': phase_info['ytd_oop'],
                    'deductible': phase_info['deductible'],
                    'description': f"Member {mbr_sk} in DEDUCTIBLE phase (YTD OOP ${phase_info['ytd_oop']:.2f} of ${phase_info['deductible']:.2f} deductible)",
                    'result': result
                })
                print(f"  ✓ Generated example")
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
    
    # Example 2: CATASTROPHIC Phase (member exceeded OOP max)
    print("\n[2] Finding CATASTROPHIC phase example...")
    catastrophic_member = get_sample_member_for_phase('CATASTROPHIC', member_phase_map)
    if catastrophic_member:
        (mbr_sk, pln_sk), phase_info = catastrophic_member
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}, OOP Max ${phase_info['oop_max']:.2f}")
        
        member_claims = ytd_claims[ytd_claims['MBR_SK'] == mbr_sk]
        if len(member_claims) > 0:
            orig_drug = member_claims.iloc[0]['PROD_SK']
            
            try:
                result = asyncio.run(financial_agent_for_candidates(
                    payload={
                        'drug_id': str(orig_drug),
                        'plan_id': str(pln_sk),
                        'fill_date': '2025-06-01',
                        'member_id': str(mbr_sk)
                    },
                    candidate_ids=['1033', '1011']
                ))
                examples.append({
                    'phase': 'CATASTROPHIC',
                    'member_id': mbr_sk,
                    'plan_id': pln_sk,
                    'original_drug': orig_drug,
                    'ytd_oop': phase_info['ytd_oop'],
                    'oop_max': phase_info['oop_max'],
                    'description': f"Member {mbr_sk} in CATASTROPHIC phase (YTD OOP ${phase_info['ytd_oop']:.2f} exceeds max ${phase_info['oop_max']:.2f})",
                    'result': result
                })
                print(f"  ✓ Generated example")
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
    
    # Example 3: INITIAL_COVERAGE with member_id (various decision types)
    print("\n[3] Finding INITIAL_COVERAGE phase example...")
    initial_member = get_sample_member_for_phase('INITIAL_COVERAGE', member_phase_map)
    if initial_member:
        (mbr_sk, pln_sk), phase_info = initial_member
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}")
        
        member_claims = ytd_claims[ytd_claims['MBR_SK'] == mbr_sk]
        if len(member_claims) > 0:
            orig_drug = member_claims.iloc[0]['PROD_SK']
            
            try:
                result = asyncio.run(financial_agent_for_candidates(
                    payload={
                        'drug_id': str(orig_drug),
                        'plan_id': str(pln_sk),
                        'fill_date': '2025-06-01',
                        'member_id': str(mbr_sk)
                    },
                    candidate_ids=['1033', '1011', '1008']  # Mix of cheaper, cheaper, more expensive
                ))
                examples.append({
                    'phase': 'INITIAL_COVERAGE',
                    'member_id': mbr_sk,
                    'plan_id': pln_sk,
                    'original_drug': orig_drug,
                    'ytd_oop': phase_info['ytd_oop'],
                    'description': f"Member {mbr_sk} in INITIAL_COVERAGE phase (YTD OOP ${phase_info['ytd_oop']:.2f})",
                    'result': result
                })
                print(f"  ✓ Generated example")
            except Exception as e:
                print(f"  ✗ Error: {str(e)}")
    
    # Example 4: No member_id (baseline for comparison)
    print("\n[4] Generating NO member_id example (baseline)...")
    try:
        result = asyncio.run(financial_agent_for_candidates(
            payload={
                'drug_id': '1018',
                'plan_id': '3010',
                'fill_date': '2025-06-01'
            },
            candidate_ids=['1033', '1011', '1008']
        ))
        examples.append({
            'phase': 'INITIAL_COVERAGE (baseline)',
            'member_id': None,
            'plan_id': 3010,
            'original_drug': 1018,
            'ytd_oop': None,
            'description': "No member_id supplied - defaults to INITIAL_COVERAGE with no YTD OOP tracking",
            'result': result
        })
        print(f"  ✓ Generated example")
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
    
    return examples

def format_presentation(examples):
    """Format examples for manager presentation."""
    output = []
    output.append("=" * 100)
    output.append("FINANCIAL AGENT EXAMPLES FOR MANAGER PRESENTATION")
    output.append("Date Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    output.append("=" * 100)
    output.append("")
    
    for idx, example in enumerate(examples, 1):
        output.append(f"\n{'=' * 100}")
        output.append(f"EXAMPLE {idx}: {example['phase']}")
        output.append(f"{'=' * 100}")
        output.append(f"Description: {example['description']}")
        output.append(f"Member ID: {example['member_id']}")
        output.append(f"Plan ID: {example['plan_id']}")
        output.append(f"Original Drug: {example['original_drug']}")
        if example.get('ytd_oop') is not None:
            output.append(f"YTD Out-of-Pocket: ${example['ytd_oop']:.2f}")
        if example.get('deductible'):
            output.append(f"Deductible: ${example['deductible']:.2f}")
        if example.get('oop_max'):
            output.append(f"OOP Maximum: ${example['oop_max']:.2f}")
        
        output.append("")
        output.append("CANDIDATE COMPARISONS:")
        output.append("-" * 100)
        
        # Result is a list of candidate dicts
        if isinstance(example['result'], list):
            for idx_cand, candidate_result in enumerate(example['result'], 1):
                if isinstance(candidate_result, dict):
                    output.append(f"\nCandidate {idx_cand}: Drug ID {candidate_result.get('drug_id', 'N/A')}")
                    output.append(f"  Coverage: {'Covered' if candidate_result.get('covered') else 'Not Covered'}")
                    output.append(f"  Tier: {candidate_result.get('tier', 'N/A')}")
                    
                    final_cost = candidate_result.get('final_cost')
                    final_cost_str = f"${final_cost:.2f}" if final_cost is not None else "N/A"
                    output.append(f"  Final Cost: {final_cost_str}")
                    
                    patient_pay = candidate_result.get('estimated_patient_pay')
                    patient_pay_str = f"${patient_pay:.2f}" if patient_pay is not None else "N/A"
                    output.append(f"  Patient Pay: {patient_pay_str}")
                    
                    orig_patient_pay = candidate_result.get('original_patient_pay')
                    orig_patient_pay_str = f"${orig_patient_pay:.2f}" if orig_patient_pay is not None else "N/A"
                    output.append(f"  Original Patient Pay: {orig_patient_pay_str}")
                    
                    savings = candidate_result.get('estimated_savings')
                    savings_str = f"${savings:.2f}" if savings is not None else "N/A"
                    output.append(f"  Estimated Savings: {savings_str}")
                    
                    savings_pct = candidate_result.get('savings_pct')
                    savings_pct_str = f"{savings_pct*100:.1f}%" if savings_pct is not None else "N/A"
                    output.append(f"  Savings %: {savings_pct_str}")
                    
                    output.append(f"  Score: {candidate_result.get('score', 'N/A')}")
                    if 'summary' in candidate_result:
                        summary = candidate_result['summary']
                        output.append(f"  Decision: {summary.get('decision', 'N/A').upper()}")
                        output.append(f"  Reason: {summary.get('reason', 'N/A')}")
                    output.append("")
        
        output.append("")
        output.append("FULL JSON OUTPUT:")
        output.append("-" * 100)
        result_json = json.dumps(example['result'], indent=2)
        output.append(result_json)
        output.append("")
    
    return "\n".join(output)

if __name__ == '__main__':
    try:
        print("\nGenerating comprehensive Financial Agent examples...\n")
        examples = generate_examples()
        
        print(f"\n\n{'=' * 80}")
        print(f"Generated {len(examples)} examples")
        print(f"{'=' * 80}\n")
        
        # Format for presentation
        presentation = format_presentation(examples)
        
        # Save to file
        output_file = os.path.join(os.path.dirname(__file__), 'FINANCIAL_AGENT_EXAMPLES.md')
        with open(output_file, 'w') as f:
            f.write(presentation)
        
        print(f"✓ Saved presentation to: {output_file}\n")
        
        # Also print to console
        print(presentation)
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
