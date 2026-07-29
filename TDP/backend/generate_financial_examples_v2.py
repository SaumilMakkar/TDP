#!/usr/bin/env python3
"""
Generate comprehensive Financial Agent examples covering all phases and decision branches.

Enhanced version that finds diverse scenarios:
- DEDUCTIBLE phase with priceable drugs
- CATASTROPHIC phase with priceable drugs  
- INITIAL_COVERAGE with member_id
- Various decision branches (cheaper, more expensive, not covered, unpriceable)
"""

import os
import sys
import json
import pandas as pd
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
sys.path.insert(0, os.path.dirname(__file__))

from agents.financial_agent import financial_agent_for_candidates

def load_data():
    """Load all necessary data files."""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    claims_df = pd.read_csv(os.path.join(data_dir, 'F_CLM_TRANSACTION.csv'))
    plans_df = pd.read_csv(os.path.join(data_dir, 'v_d_plan.csv'))
    pricing_df = pd.read_csv(os.path.join(data_dir, 'v_d_drug_pricing.csv'))
    member_df = pd.read_csv(os.path.join(data_dir, 'v_d_member.csv'))
    plan_drug_status_df = pd.read_csv(os.path.join(data_dir, 'v_d_plan_drug_status.csv'))
    
    claims_df['FILLED_DT'] = pd.to_datetime(claims_df['FILLED_DT'])
    pricing_df['PRICE_EFF_FROM_DT'] = pd.to_datetime(pricing_df['PRICE_EFF_FROM_DT'])
    pricing_df['PRICE_EFF_THRU_DT'] = pd.to_datetime(pricing_df['PRICE_EFF_THRU_DT'])
    
    return claims_df, plans_df, pricing_df, member_df, plan_drug_status_df

def get_covered_drugs_for_plan(pln_sk, plan_drug_status_df):
    """Get drugs covered under a plan."""
    covered = plan_drug_status_df[plan_drug_status_df['PLN_SK'] == pln_sk]['PROD_SK'].unique()
    return set(str(int(c)) for c in covered)

def analyze_member_phases():
    """Analyze members to find those in different phases."""
    claims_df, plans_df, pricing_df, member_df, plan_drug_status_df = load_data()
    
    reference_date = pd.to_datetime('2025-06-01')
    year_start = pd.to_datetime('2025-01-01')
    
    ytd_claims = claims_df[
        (claims_df['FILLED_DT'] >= year_start) & 
        (claims_df['FILLED_DT'] <= reference_date) &
        (claims_df['CLAIM_STAT_ID'] == 'PAID')
    ].copy()
    
    member_phase_map = {}
    for mbr_sk, member_claims in ytd_claims.groupby('MBR_SK'):
        for pln_sk, plan_claims in member_claims.groupby('PLN_SK'):
            ytd_oop = plan_claims['OOP_APPLIED_AMT'].sum()
            plan_row = plans_df[plans_df['PLN_SK'] == pln_sk]
            
            if len(plan_row) > 0:
                plan_row = plan_row.iloc[0]
                deductible = plan_row['DEDUCTIBLE_AMT']
                oop_max = plan_row['MAX_OOP_AMT']
                
                phase = 'INITIAL_COVERAGE'
                if ytd_oop < deductible:
                    phase = 'DEDUCTIBLE'
                elif ytd_oop >= oop_max:
                    phase = 'CATASTROPHIC'
                
                # Store claims for this member-plan to find filled drugs
                member_claims_for_pair = plan_claims
                filled_drugs = member_claims_for_pair['PROD_SK'].unique()
                
                key = (mbr_sk, pln_sk)
                member_phase_map[key] = {
                    'ytd_oop': ytd_oop,
                    'deductible': deductible,
                    'oop_max': oop_max,
                    'phase': phase,
                    'plan_id': pln_sk,
                    'filled_drugs': filled_drugs,
                    'filled_claims': member_claims_for_pair
                }
    
    return member_phase_map, ytd_claims, plans_df, plan_drug_status_df

def get_sample_members_for_phase(phase, member_phase_map, n=3):
    """Get multiple sample members in the requested phase."""
    candidates = [(k, v) for k, v in member_phase_map.items() if v['phase'] == phase]
    if candidates:
        candidates.sort(key=lambda x: x[1]['ytd_oop'], reverse=True)
        return candidates[:n]
    return []

async def generate_example(member_sk, pln_sk, orig_drug, candidate_ids, phase_info, phase_name):
    """Generate a single example."""
    try:
        result = await financial_agent_for_candidates(
            payload={
                'drug_id': str(orig_drug),
                'plan_id': str(pln_sk),
                'fill_date': '2025-06-01',
                'member_id': str(member_sk)
            },
            candidate_ids=[str(cid) for cid in candidate_ids]
        )
        return {
            'phase': phase_name,
            'member_id': member_sk,
            'plan_id': pln_sk,
            'original_drug': orig_drug,
            'ytd_oop': phase_info.get('ytd_oop'),
            'deductible': phase_info.get('deductible'),
            'oop_max': phase_info.get('oop_max'),
            'description': f"Member {member_sk} in {phase_name} phase (YTD OOP ${phase_info.get('ytd_oop', 0):.2f})",
            'result': result
        }
    except Exception as e:
        print(f"    Error generating example: {str(e)}")
        return None

async def generate_examples():
    """Generate comprehensive Financial Agent examples."""
    print("=" * 80)
    print("FINANCIAL AGENT EXAMPLE GENERATOR FOR MANAGER PRESENTATION")
    print("=" * 80)
    print()
    
    member_phase_map, ytd_claims, plans_df, plan_drug_status_df = analyze_member_phases()
    
    print("Analyzing member phases...")
    print(f"  Found {len(member_phase_map)} member-plan combinations with YTD OOP data")
    
    examples = []
    
    # 1. DEDUCTIBLE Examples
    print("\n[1] Finding DEDUCTIBLE phase examples...")
    deductible_members = get_sample_members_for_phase('DEDUCTIBLE', member_phase_map, n=2)
    for (mbr_sk, pln_sk), phase_info in deductible_members:
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}, Deductible ${phase_info['deductible']:.2f}")
        
        # Try to find alternatives from candidates 1033, 1011 that are covered
        covered_drugs = get_covered_drugs_for_plan(pln_sk, plan_drug_status_df)
        orig_drug = str(int(phase_info['filled_drugs'][0]))
        
        # Use candidates that are covered under this plan
        candidate_ids = [cid for cid in ['1033', '1011', '1008', '1007', '1006'] if cid in covered_drugs]
        if not candidate_ids:
            candidate_ids = ['1033', '1011']  # Fallback
        
        example = await generate_example(mbr_sk, pln_sk, orig_drug, candidate_ids[:2], phase_info, "DEDUCTIBLE")
        if example:
            examples.append(example)
            print(f"    ✓ Generated example")
    
    # 2. CATASTROPHIC Examples
    print("\n[2] Finding CATASTROPHIC phase examples...")
    catastrophic_members = get_sample_members_for_phase('CATASTROPHIC', member_phase_map, n=2)
    for (mbr_sk, pln_sk), phase_info in catastrophic_members:
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}, OOP Max ${phase_info['oop_max']:.2f}")
        
        covered_drugs = get_covered_drugs_for_plan(pln_sk, plan_drug_status_df)
        orig_drug = str(int(phase_info['filled_drugs'][0]))
        
        candidate_ids = [cid for cid in ['1033', '1011', '1008', '1007', '1006'] if cid in covered_drugs]
        if not candidate_ids:
            candidate_ids = ['1033', '1011']
        
        example = await generate_example(mbr_sk, pln_sk, orig_drug, candidate_ids[:2], phase_info, "CATASTROPHIC")
        if example:
            examples.append(example)
            print(f"    ✓ Generated example")
    
    # 3. INITIAL_COVERAGE Examples
    print("\n[3] Finding INITIAL_COVERAGE phase examples...")
    initial_members = get_sample_members_for_phase('INITIAL_COVERAGE', member_phase_map, n=2)
    for (mbr_sk, pln_sk), phase_info in initial_members:
        print(f"  ✓ Member {mbr_sk}, Plan {pln_sk}: YTD OOP ${phase_info['ytd_oop']:.2f}")
        
        covered_drugs = get_covered_drugs_for_plan(pln_sk, plan_drug_status_df)
        orig_drug = str(int(phase_info['filled_drugs'][0]))
        
        # Mix of covered and uncovered
        candidate_ids = [cid for cid in ['1033', '1011', '1008', '1007', '1006'] if cid in covered_drugs]
        if not candidate_ids:
            candidate_ids = ['1033', '1011', '1008']
        
        example = await generate_example(mbr_sk, pln_sk, orig_drug, candidate_ids[:3], phase_info, "INITIAL_COVERAGE")
        if example:
            examples.append(example)
            print(f"    ✓ Generated example")
    
    # 4. Baseline (no member_id)
    print("\n[4] Generating baseline example (no member_id)...")
    try:
        result = await financial_agent_for_candidates(
            payload={
                'drug_id': '1018',
                'plan_id': '3010',
                'fill_date': '2025-06-01'
            },
            candidate_ids=['1033', '1011', '1008']
        )
        examples.append({
            'phase': 'INITIAL_COVERAGE (baseline)',
            'member_id': None,
            'plan_id': '3010',
            'original_drug': '1018',
            'ytd_oop': None,
            'description': "No member_id supplied - defaults to INITIAL_COVERAGE with no YTD OOP tracking",
            'result': result
        })
        print(f"  ✓ Generated baseline example")
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
    output.append("OVERVIEW:")
    output.append("-" * 100)
    output.append(f"Total Examples: {len(examples)}")
    output.append("")
    
    phase_counts = {}
    for example in examples:
        phase = example['phase']
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
    
    for phase, count in sorted(phase_counts.items()):
        output.append(f"  • {phase}: {count} example(s)")
    
    output.append("")
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
                    
                    score = candidate_result.get('score')
                    score_str = f"{score:.3f}" if score is not None else "N/A"
                    output.append(f"  Score: {score_str}")
                    
                    if 'summary' in candidate_result:
                        summary = candidate_result['summary']
                        output.append(f"  Decision: {summary.get('decision', 'N/A').upper()}")
                        reason = summary.get('reason', 'N/A')
                        # Truncate long reasons
                        if len(reason) > 120:
                            reason = reason[:117] + "..."
                        output.append(f"  Reason: {reason}")
                    output.append("")
        
        output.append("")
    
    return "\n".join(output)

async def main():
    try:
        print("\nGenerating comprehensive Financial Agent examples...\n")
        examples = await generate_examples()
        
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
        
        # Also print to console (truncated)
        lines = presentation.split('\n')
        for line in lines[:150]:  # Print first 150 lines
            print(line)
        if len(lines) > 150:
            print(f"\n... ({len(lines) - 150} more lines) ...")
            print("\n✓ Full presentation saved to FINANCIAL_AGENT_EXAMPLES.md")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
