from __future__ import annotations

def format_semester_label(semeseter_num: int, semesters_per_year: int):
    # Converting a global semester index (1...n) into UI friendly label
    # If semesters_per_year is given, labels become
    # 1 -> year 1 - Term
    if not semesters_per_year or semesters_per_year <1:
        return f"Semester {semeseter_num}"
    
    year = (semeseter_num - 1) // semesters_per_year + 1
    term = (semeseter_num - 1) % semesters_per_year + 1
    return f"Year {year} - Semester {term}"
