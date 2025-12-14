import json

def save_to_aez_file(
    filepath: str,
    eq_parametric: dict,
    earphone_name: str,
    earphone_curve: list,
    target_name: str,
    target_curve: list
):
    data = {
        "equalizer": {
            "parametric": eq_parametric
        },
        "headphone": {
            "name": earphone_name,
            "curve": earphone_curve
        },
        "target": {
            "name": target_name,
            "curve": target_curve
        }
    }

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except IOError as e:
        print(f"Erreur lors de l'écriture du fichier : {e}")