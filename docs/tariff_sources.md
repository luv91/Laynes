# Tariff Data Sources Repository

This document catalogs all government sources used for tariff rate data, with links, access restrictions, and key information extracted.

**Last Updated:** December 7, 2025

---

## Quick Reference: Current Rates (Dec 2025)

| Tariff Program | Rate | Chapter 99 Code | Source |
|----------------|------|-----------------|--------|
| Base Duty (HTS 8544.42.90.90) | 2.6% | - | USITC HTS |
| Section 301 (List 3) | 25% | 9903.88.03 | USTR |
| Section 232 Steel | 50% | 9903.80.01 | CBP/Proclamation 10895 |
| Section 232 Aluminum | 25% | 9903.85.08 | CBP/Proclamation 10896 |
| Section 232 Copper | 25% | 9903.78.01 | CBP |
| IEEPA Fentanyl | 10% | 9903.01.25 | CBP IEEPA FAQ |
| IEEPA Reciprocal (paid) | 10% | 9903.01.33 | CBP IEEPA FAQ |
| IEEPA Reciprocal (disclaim) | 0% | 9903.01.25 | CBP IEEPA FAQ |

---

## Source 1: USITC Harmonized Tariff Schedule

### Link
**URL:** https://hts.usitc.gov/

### Access
- **Public:** Yes, freely accessible
- **API:** REST API available at `https://hts.usitc.gov/reststop/`
- **Format:** Web search, PDF downloads, REST API
- **Restrictions:** None

### Key Information
- Base duty rates for all HTS codes
- Column 1 General rates (MFN/NTR)
- Special program rates (GSP, FTA, etc.)
- Chapter 99 additional duties

### How to Use
```
Search: https://hts.usitc.gov/search?query=8544.42.90.90
API: https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+85
```

### Data Extracted
| HTS Code | Description | Base Rate |
|----------|-------------|-----------|
| 8544.42.90.90 | Insulated electric conductors, fitted with connectors | 2.6% |
| 8539.50.00.00 | LED lamps | Free |

---

## Source 2: USTR Section 301 Tariff Actions

### Link
**URL:** https://ustr.gov/issue-areas/enforcement/section-301-investigations/tariff-actions

### Access
- **Public:** Yes
- **Search Tool:** https://www.ustr.gov/issue-areas/enforcement/section-301-investigations/search
- **Format:** PDF notices, searchable database
- **Restrictions:** None

### Key Information
- Which HTS codes are on Lists 1-4
- Section 301 duty rates (7.5%, 25%, etc.)
- Exclusions and extensions
- Effective dates

### How to Use
Search by 8-digit HTS code to find:
- List assignment (List 1, 2, 3, 4A, 4B)
- Chapter 99 code
- Duty rate
- Any exclusions

### Data Extracted
| List | HTS Codes | Chapter 99 | Rate | Effective |
|------|-----------|------------|------|-----------|
| List 1 ($34B) | Various | 9903.88.01 | 25% | Jul 6, 2018 |
| List 2 ($16B) | Various | 9903.88.02 | 25% | Aug 23, 2018 |
| List 3 ($200B) | 85444290, etc. | 9903.88.03 | 25% | Sep 24, 2018 |
| List 4A ($120B) | Various | 9903.88.15 | 7.5% | Sep 1, 2019 |

### Related Links
- [C.H. Robinson Guide](https://www.chrobinson.com/en-us/resources/resource-center/guides/section-301-china-tariff-guide/)
- [USA Customs Clearance Guide](https://usacustomsclearance.com/process/section-301-tariffs-a-comprehensive-guide/)

---

## Source 3: CBP Section 232 FAQ

### Link
**URL:** https://www.cbp.gov/trade/programs-administration/entry-summary/232-tariffs-aluminum-and-steel-faqs

### Access
- **Public:** Yes
- **Format:** FAQ page, links to CSMS messages
- **Restrictions:** None

### Key Information
- Steel/Aluminum tariff rates
- Derivative product rules
- Filing requirements
- Chapter 99 codes for claim/disclaim

### Data Extracted (December 2025)
| Material | Rate | Claim Code | Disclaim Code | Proclamation |
|----------|------|------------|---------------|--------------|
| Steel | 50% | 9903.80.01 | 9903.80.02 | 10895 |
| Aluminum | 25% | 9903.85.08 | 9903.85.09 | 10896 |
| Copper | 25% | 9903.78.01 | 9903.78.02 | - |

### Rate History
| Date | Event | Steel Rate | Aluminum Rate |
|------|-------|------------|---------------|
| Mar 23, 2018 | Original | 25% | 10% |
| Mar 12, 2025 | Increase (Proc. 10895/10896) | 50% | 25% |

### Related Links
- [White & Case Analysis](https://www.whitecase.com/insight-alert/trump-administration-increases-steel-and-aluminum-section-232-tariffs-50-and-narrows)
- [Federal Register - Proclamation 10895](https://www.federalregister.gov/documents/2025/05/02/2025-07676/adoption-and-procedures-of-the-section-232-steel-and-aluminum-tariff-inclusions-process)

---

## Source 4: CBP IEEPA FAQ

### Link
**URL:** https://www.cbp.gov/trade/programs-administration/trade-remedies/IEEPA-FAQ

### Access
- **Public:** Yes
- **Format:** FAQ page
- **Restrictions:** None

### Key Information
- IEEPA Fentanyl tariff rates
- IEEPA Reciprocal tariff rates
- Chapter 99 codes
- Filing guidance

### Data Extracted (December 2025)
| Program | Rate | Chapter 99 | Effective Date |
|---------|------|------------|----------------|
| IEEPA Fentanyl | 10% | 9903.01.25 | Nov 10, 2025 |
| IEEPA Reciprocal (paid) | 10% | 9903.01.33 | Current |
| IEEPA Reciprocal (disclaim) | 0% | 9903.01.25 | Current |

### Rate History
| Date | Event | Fentanyl Rate |
|------|-------|---------------|
| Feb 4, 2025 | Initial | 10% |
| Mar 3, 2025 | Increase | 20% |
| Nov 10, 2025 | Reduction (US-China deal) | 10% |

### Related Links
- [Thompson Coburn Analysis](https://www.thompsoncoburn.com/insights/58-november-4-2025-reducing-the-20-ieepa-fentanyl-tariffs-on-china-to-10-reciprocal-tariffs-on-china-remain-at-10-until-november-2026/)
- [White House EO - Nov 2025](https://www.whitehouse.gov/presidential-actions/2025/11/modifying-duties-addressing-the-synthetic-opioid-supply-chain-in-the-peoples-republic-of-china/)

---

## Source 5: CBP CSMS Messages

### Link
**URL:** https://content.govdelivery.com/accounts/USDHSCBP/bulletins/

### Access
- **Public:** Yes
- **Format:** Email bulletins, web archive
- **Restrictions:** None

### Key Information
- Real-time tariff updates
- Filing guidance changes
- New Chapter 99 codes
- Effective dates

### Key CSMS Messages Referenced
| CSMS # | Topic | Date |
|--------|-------|------|
| 63577329 | Section 301 Four Year Review | 2024 |
| 65236374 | Steel Derivative Products Update | 2025 |
| 39587858 | HTS Line Ordering | - |

---

## Source 6: Federal Register

### Link
**URL:** https://www.federalregister.gov/

### Access
- **Public:** Yes
- **API:** Available
- **Format:** Official notices, searchable
- **Restrictions:** None

### Key Information
- Presidential Proclamations
- USTR Notices
- CBP Regulations
- Official legal text

### Key Documents
| Document | Topic | Citation |
|----------|-------|----------|
| Proclamation 10895 | Steel 232 Increase | 2025 |
| Proclamation 10896 | Aluminum 232 Increase | 2025 |
| EO 14228 | IEEPA Fentanyl Increase | Mar 3, 2025 |

---

## Source 7: HTS Hub (Third Party)

### Link
**URL:** https://www.htshub.com/

### Access
- **Public:** Yes (limited)
- **Format:** Web search
- **Restrictions:** Some features may require registration

### Key Information
- HTS code lookup
- Duty rates
- Chapter 99 cross-references
- Country-specific rates

### Example Query
```
https://www.htshub.com/us-hs/detail/8544429090
```

### Data Extracted
| HTS Code | General Rate | Special Programs | China Additional |
|----------|--------------|------------------|------------------|
| 8544.42.90.90 | 2.6% | Free (A,AU,B,etc.) | See 9903.88.69 |

---

## Source 8: Flexport Tariff Simulator

### Link
**URL:** https://tariffs.flexport.com/

### Access
- **Public:** Yes
- **Format:** Interactive calculator
- **Restrictions:** None

### Key Information
- Total landed cost calculations
- Tariff stacking
- Country-specific rates

### Notes
- Good for verification
- May not always be current
- Use for cross-checking

---

## Data Update Schedule

| Source | Update Frequency | How to Monitor |
|--------|------------------|----------------|
| USITC HTS | Quarterly revisions | Check revision number |
| USTR 301 | As needed (notices) | Subscribe to USTR updates |
| CBP 232 | As needed (proclamations) | Subscribe to CSMS |
| CBP IEEPA | Frequently (2025) | Subscribe to CSMS |
| Federal Register | Daily | Search by topic |

---

## API Access Notes

### USITC REST API
```bash
# Get Chapter 85 data
curl "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=Chapter+85"

# Get China Tariffs document
curl "https://hts.usitc.gov/reststop/file?release=currentRelease&filename=China+Tariffs"
```

### Limitations
- No real-time API for current rates
- Must parse PDF/HTML for rates
- Manual updates required for rate changes

---

## Recommended Update Process

1. **Weekly:** Check CBP CSMS for new messages
2. **Monthly:** Verify rates against USITC HTS
3. **On News:** Check for Executive Orders affecting tariffs
4. **Quarterly:** Full audit against all sources

---

## Contact Information

| Agency | Contact | Purpose |
|--------|---------|---------|
| CBP Trade | traderemedy@cbp.dhs.gov | Tariff questions |
| USTR | Section 301 hotline | 301 exclusions |
| USITC | HTS helpdesk | Classification questions |
