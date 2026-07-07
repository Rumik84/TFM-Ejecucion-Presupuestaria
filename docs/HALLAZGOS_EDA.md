# Hallazgos del EDA y justificación de la metodología

> Generado a partir de `reports/eda/eda_report.html` (feature store núcleo, saneado).
> Cubre los puntos del feedback: datos limpios (R1), descriptivos (R2), distribución (R3),
> supuestos estadísticos (R4) y vínculo EDA ↔ objetivos/algoritmos (R6).

## 1. Datos limpios (evidencia)

Sobre **12.494** filas del feature store se eliminaron **75** con importes físicamente
imposibles (|importe| > 1×10¹¹ €) por errores de parseo → **12.419 filas limpias**.

| CCAA | Filas | Corruptas | % |
|------|------:|----------:|----:|
| AGE | 3.854 | 22 | 0,57 |
| País Vasco | 101 | 17 | 16,83 |
| Aragón | 8.157 | 11 | 0,14 |
| C.-La Mancha | 41 | 11 | 26,83 |
| Asturias | 12 | 7 | 58,33 |
| Cataluña | 139 | 7 | 5,04 |

La corrupción no se limitaba a Asturias; el saneo se aplica de forma sistemática y
trazable antes de cualquier cálculo estadístico.

## 2. Estadísticos descriptivos (variables clave)

| Variable | n | media | mediana | desv. típica | máx |
|----------|--:|------:|--------:|-------------:|----:|
| PRE (€) | 12.182 | 699,2 M | 13,4 M | 4.240 M | 99.000 M |
| OBR (€) | 6.598 | 562,3 M | 10,3 M | 3.354 M | 91.292 M |
| CRE (€) | 6.690 | 438,6 M | 10,2 M | 2.493 M | 91.145 M |
| brecha_pct | 6.371 | −1,53 | 0,26 | 36,2 | 1,00 |
| ejecutado_pct | 6.413 | 1,32 | 0,93 | 4,12 | 50,5 |
| pago_pct | 5.993 | 0,80 | 0,91 | 0,85 | 50,5 |

**Lectura:** media ≫ mediana en todos los importes → distribución muy asimétrica a la
derecha (pocas entidades grandes concentran el gasto). La ejecución típica (mediana)
ronda el **93 %** del crédito disponible; la brecha mediana es del **26 %** del presupuesto.

## 3. Supuestos estadísticos

### Normalidad (se rechaza en todas las variables, α=0,05)

| Variable | Shapiro W | p | Asimetría | Curtosis | ¿Normal? |
|----------|----------:|--:|----------:|---------:|:--------:|
| OBR | 0,15 | 5,8×10⁻⁹² | 13,51 | 232,4 | No |
| log(1+OBR) | 0,99 | 7,9×10⁻¹⁸ | −0,12 | 0,44 | No (casi) |
| ejecutado_pct | 0,43 | 4,5×10⁻⁸³ | 5,07 | 30,7 | No |
| brecha_pct | 0,54 | 4,0×10⁻⁷⁸ | −3,47 | 12,3 | No |

OBR es fuertemente no normal (asimetría 13,5; curtosis 232). La **transformación
logarítmica** lo acerca mucho a la normalidad (asimetría −0,12, curtosis 0,44), aunque
con n≈6.500 los tests siguen rechazando H₀.

### Homocedasticidad (se rechaza → heterocedástico)

| Test | Estadístico | p | Conclusión |
|------|------------:|--:|:----------:|
| Levene (ejecutado_pct entre capítulos) | 25,43 | 8,2×10⁻³⁹ | Heterocedástico |
| Breusch-Pagan (OBR ~ PRE + CRE) | 250,63 | 3,8×10⁻⁵⁵ | Heterocedástico |

## 4. Vínculo hallazgos → decisiones analíticas (R6)

| Hallazgo del EDA | Decisión metodológica |
|------------------|------------------------|
| OBR no normal + heterocedástico | Modelos basados en árboles (Random Forest, XGBoost, LightGBM) en lugar de OLS, que asume normalidad y varianza constante de residuos |
| Asimetría extrema de importes | Transformación log(1+OBR) como objetivo alternativo / variable derivada |
| ejecutado_pct mediana ≈ 0,93 y acotada | Problema bien planteado: la ejecución es predecible a partir de PRE/CRE e histórico |
| Cobertura muy desigual entre CCAA | Modelar solo las CCAA del núcleo (PRE+OBR); el resto, análisis descriptivo |
| Alta autocorrelación OBR (lags) | Features temporales (obr_lag_1..4, rolling) son predictoras clave |
| Estacionalidad trimestral | Features cíclicas q_sin / q_cos |
| Heterocedasticidad por capítulo | Métricas de error relativas (MAPE) además de absolutas (MAE, RMSE); posible modelado por segmento |

**Conclusión de factibilidad:** los datos, una vez saneados, presentan estructura
suficiente (relaciones PRE→CRE→OBR, autocorrelación temporal, estacionalidad) para
sustentar el modelado predictivo, y sus propiedades estadísticas (no normalidad,
heterocedasticidad) justifican formalmente la elección de algoritmos no paramétricos.
</content>
