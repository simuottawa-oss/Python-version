# Shared Material inspector

The Scene and Structural Properties panels use one Material section and one
catalog. Select a preset, use **Edit as Custom**, or inherit **From Part**.
The display uses GPa and kg/m³; saved snapshots use Pa, a dimensionless Poisson
ratio, and kg/m³. Saved numerical values are authoritative when reopening, even
if a later catalog changes. A changed/unknown preset snapshot displays as Custom.

| Preset | E (GPa) | Poisson ratio | Density (kg/m³) |
| --- | ---: | ---: | ---: |
| A36 steel | 200 | 0.30 | 7850 |
| 304 stainless steel | 200 | 0.30 | 7900 |
| 6061-T6 aluminum | 69 | 0.33 | 2700 |
| Ti-6Al-4V titanium | 114 | 0.31 | 4420 |
| C110 copper | 117 | 0.328125 | 8940 |
| ABS, unfilled | 2.3 | 0.35 | 1040 |
| Polycarbonate, unfilled | 2.4 | 0.37 | 1200 |

These are typical room-temperature, isotropic modelling values. They do not
include yield strength or determine whether a part will fail. For polymers,
processing, rate, temperature and grade affect stiffness; the default Poisson
ratios of ABS and polycarbonate are explicit modelling assumptions. Aluminum's
0.33 and stainless steel's 0.30 are nominal isotropic approximations. Custom
allows replacing any assumption with measurements for the actual material.

Sources and choices:

- [SSAB steel questions](https://www.ssab.com/en/support/product-material-data/steel/20-questions)
  documents typical steel properties including Poisson ratio near 0.30. The A36
  entry uses nominal engineering steel stiffness and density.
- [Outokumpu cold-rolled austenitic EPD](https://otke-cdn.outokumpu.com/-/media/files/sustainability/epd-cold-rolled-austenitic.pdf?modified=20241112103155&revision=c2c8d414-293e-41b4-a5ac-2fb17396483e)
  gives 200 GPa and 7900 kg/m³ for austenitic grades including 304.
- [Hydro Alloy 6061](https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf)
  provides typical 6061 physical properties. The preset rounds stiffness to 69 GPa
  and density to 2700 kg/m³.
- [TIMET TIMETAL 6-4](https://www.timet.com/assets/local/documents/datasheets/alphaandbetaalloys/6-4.pdf)
  gives 4420 kg/m³, Poisson ratio 0.31 and a room-temperature modulus range of
  107–122 GPa. The preset uses a representative 114 GPa within that range.
- [thyssenkrupp copper guide](https://ucpcdn.thyssenkrupp.com/_legacy/UCPthyssenkruppBAMXNA/assets.files/tkmna_com/products/collateral/copper-and-alloys-guide.pdf)
  lists C110 tension/shear moduli of 17000/6400 ksi. The preset rounds E to
  117 GPa and derives ν = E/(2G) − 1 = 0.328125 from their ratio; density is nominal.
- [INEOS Styrolution Terluran GP-22](https://www.ineos-styrolution.com/Product/Terluran_Terluran-GP-22_SKU300600120827_lang_en_GB.html)
  supplies the representative unfilled ABS modulus of 2300 MPa and density of
  1040 kg/m³. The ABS preset uses assumed ν = 0.35.
- [Covestro Makrolon 2405](https://www.covestro.com/en/products/makrolon-2405-00945088)
  supplies representative polycarbonate modulus of 2400 MPa and density of
  1200 kg/m³. The polycarbonate preset uses assumed ν = 0.37.

Scene assignments are instance overrides: source `.simuOPart` files are not
rewritten. Density changes affect native parts with density-based mass; explicit
mass remains authoritative. Legacy meshes keep their existing 1 kg dynamic mass
fallback because their solid volume is not established. Friction and bounce
remain independent Physics settings. Old scenes without an assignment inherit
the source part as before.

Structural analysis requires E > 0 and −1 < ν < 0.5. Gravity also requires a
positive density. From Part never invents missing elastic constants from a name.
